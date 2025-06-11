import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

import re
import pandas as pd
import numpy as np
import faiss
import pickle
import PyPDF2
from tqdm import tqdm
from sklearn.feature_extraction.text import TfidfVectorizer
from langchain.text_splitter import RecursiveCharacterTextSplitter
from web.utils.config_loader import config
from web.utils.openai_client import OpenAIClientManager
from web.utils.local_embedding_client import LocalEmbeddingClient

class DataProcessor:
    """
    Processes PDF documents for the SFDA regulatory chatbot.
    Extracts text, chunks it, generates embeddings, and creates a FAISS index.
    """
    
    def __init__(self):
        """Initialize the data processor."""
        self.data_dir = "data"
        self.processed_data_dir = "web/processed_data"
        self.regulatory_dir = os.path.join(self.data_dir, "regulatory")
        self.pharmacovigilance_dir = os.path.join(self.data_dir, "pharmacovigilance")

        # Load settings from config
        self.chunk_size = config.get("data_processing", "chunk_size", 7000)
        self.chunk_overlap = config.get("data_processing", "chunk_overlap", 400)
        self.embedding_batch_size = config.get("data_processing", "embedding_batch_size", 100)
        
        # Initialize embedding client based on config
        embedding_type = config.get("search_engine", "embedding_type", "local")
        if embedding_type == "openai":
            self.embedding_client = OpenAIClientManager()
            self.embedding_dimension = 1536  # OpenAI embeddings dimension
        else:
            self.embedding_client = LocalEmbeddingClient()
            self.embedding_dimension = self.embedding_client.embedding_dimension
        
        # Ensure processed data directory exists
        os.makedirs(self.processed_data_dir, exist_ok=True)
    
    def process_all_documents(self):
        """Process all documents in the data directory."""
        print("Starting document processing...")
        
        # Process documents by category
        categories = {
            "regulatory": self.regulatory_dir,
            "pharmacovigilance": self.pharmacovigilance_dir
        }
        
        all_chunks = []
        
        for category, directory in categories.items():
            print(f"Processing {category} documents...")
            
            # Check if directory exists
            if not os.path.exists(directory):
                print(f"Directory {directory} does not exist. Skipping.")
                continue
            
            # Get all PDF files in the directory
            pdf_files = [f for f in os.listdir(directory) if f.lower().endswith('.pdf')]
            
            if not pdf_files:
                print(f"No PDF files found in {directory}. Skipping.")
                continue
            
            # Process each PDF file
            for pdf_file in tqdm(pdf_files, desc=f"Processing {category} PDFs"):
                file_path = os.path.join(directory, pdf_file)
                
                # Extract text page by page
                pages_data = self._extract_text_from_pdf(file_path)
                
                # Skip if no text was extracted
                if not pages_data:
                    print(f"No text extracted from {file_path}. Skipping.")
                    continue
                
                # Split text into chunks, preserving page numbers
                chunks_with_pages = self._split_into_chunks(pages_data)
                
                # Add metadata to chunks
                for i, chunk_info in enumerate(chunks_with_pages):
                    chunk_data = {
                        "text": chunk_info["text"],
                        "category": category,
                        "document": pdf_file,
                        "page": chunk_info["page"], # Add page number
                        "chunk_id": f"{pdf_file}_p{chunk_info['page']}_{i}" # Include page in ID
                    }
                    all_chunks.append(chunk_data)
        
        if not all_chunks:
            print("No chunks were created. Please check your PDF files.")
            return False
        
        # Create dataframe from chunks
        df = pd.DataFrame(all_chunks)
        
        # Save dataframe to CSV
        df_path = os.path.join(self.processed_data_dir, "chunks_data.csv")
        df.to_csv(df_path, index=False)
        print(f"Saved {len(df)} chunks to {df_path}")
        
        # Create TF-IDF vectorizer and matrix
        print("Creating TF-IDF vectorizer and matrix...")
        tfidf_vectorizer = TfidfVectorizer(max_features=5000)
        tfidf_matrix = tfidf_vectorizer.fit_transform(df["text"])
        
        # Save TF-IDF vectorizer and matrix
        with open(os.path.join(self.processed_data_dir, "tfidf_vectorizer.pkl"), 'wb') as f:
            pickle.dump(tfidf_vectorizer, f)
        
        with open(os.path.join(self.processed_data_dir, "tfidf_matrix.pkl"), 'wb') as f:
            pickle.dump(tfidf_matrix, f)
        
        # Create FAISS index
        print("Creating FAISS index...")
        self._create_faiss_index(df)
        
        print("Document processing completed successfully.")
        return True
    
    def _extract_text_from_pdf(self, file_path):
        """
        Extract text from a PDF file.
        
        Args:
            file_path (str): Path to the PDF file

        Returns:
            list: List of dictionaries, each with 'text' and 'page' number, or empty list on error.
        """
        try:
            text_with_pages = []
            with open(file_path, 'rb') as file:
                reader = PyPDF2.PdfReader(file)
                for page_num in range(len(reader.pages)):
                    page = reader.pages[page_num]
                    page_text = page.extract_text()
                    if page_text and page_text.strip(): # Only add non-empty pages
                        cleaned_text = self._clean_text(page_text)
                        if cleaned_text: # Ensure cleaned text is not empty
                            text_with_pages.append({
                                "text": cleaned_text,
                                "page": page_num + 1 # Page numbers start from 1
                            })
            return text_with_pages
        except Exception as e:
            print(f"Error extracting text from {file_path}: {str(e)}")
            return []
    
    def _clean_text(self, text):
        """
        Clean the extracted text.
        
        Args:
            text (str): The text to clean
            
        Returns:
            str: Cleaned text
        """
        # Replace multiple newlines with a single newline
        text = re.sub(r'\n+', '\n', text)
        
        # Replace multiple spaces with a single space
        text = re.sub(r'\s+', ' ', text)
        
        # Remove any non-printable characters
        text = re.sub(r'[^\x20-\x7E\n]', '', text)
        
        return text.strip()

    def _has_table(self, text):
        """
        Detect if text contains table patterns.
        
        Args:
            text (str): Text to analyze
            
        Returns:
            bool: True if table patterns detected
        """
        patterns = [
            r'\+[-+]+\+',  # ASCII tables
            r'\|.*\|',     # Pipe tables 
            r'\s{2,}.+\s{2,}',  # Space-aligned columns
            r'<table.*?>'  # HTML tables
        ]
        return any(re.search(p, text) for p in patterns)

    def _split_into_chunks(self, pages_data):
        """
        Split text from multiple pages into overlapping chunks, preserving page numbers.
        Uses adaptive chunk sizes based on content type (tables vs regular text).

        Args:
            pages_data (list): List of dicts {'text': str, 'page': int}

        Returns:
            list: List of dicts {'text': str, 'page': int, 'chunk_type': str} representing chunks.
        """
        all_page_chunks = []

        for page_info in pages_data:
            page_text = page_info["text"]
            page_num = page_info["page"]
            
            # Determine chunk parameters based on content
            if self._has_table(page_text):
                size, overlap = 3000, 600  # Larger chunks for tables
            else:
                size, overlap = self.chunk_size, self.chunk_overlap  # Default sizes
                
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=size,
                chunk_overlap=overlap,
                length_function=len,
                is_separator_regex=False,
                separators=["\n\n", "\n", ". ", "? ", "! ", " ", ""]
            )

            try:
                chunks = text_splitter.split_text(page_text)
                for chunk in chunks:
                    if chunk and chunk.strip():
                        all_page_chunks.append({
                            "text": str(chunk),
                            "page": page_num,
                            "chunk_type": "table" if self._has_table(chunk) else "text"
                        })
            except Exception as e:
                print(f"Error splitting text for page {page_num}: {str(e)}")

        return all_page_chunks

    def _create_faiss_index(self, df):
        """
        Create a FAISS index from the document chunks.
        
        Args:
            df (pandas.DataFrame): DataFrame containing the chunks
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Get embeddings for all chunks
            embeddings = self._get_embeddings(df["text"].tolist())
            
            # Create FAISS index
            index = faiss.IndexFlatL2(self.embedding_dimension)
            index.add(embeddings)
            
            # Save the index
            os.makedirs(self.processed_data_dir, exist_ok=True)
            faiss_path = os.path.join(self.processed_data_dir, "faiss_index.bin")
            faiss.write_index(index, faiss_path)
            print(f"Saved FAISS index to {faiss_path}")
            
            return True
        
        except Exception as e:
            print(f"Error creating FAISS index: {str(e)}")
            return False
    
    def _get_embeddings(self, texts):
        """
        Get embeddings for a list of texts using configured embedding client.
        
        Args:
            texts (list): List of texts to embed
            
        Returns:
            numpy.ndarray: Array of embeddings
        """
        return self.embedding_client.get_embeddings(texts, self.embedding_batch_size)

# Main execution
if __name__ == "__main__":
    processor = DataProcessor()
    processor.process_all_documents()
