import os
import sys
from dotenv import load_dotenv
from ..services.data_processing import DataProcessor
from ..services.search_engine import ImprovedSearchEngine

# Load environment variables
load_dotenv()

def test_data_processing():
    """Test the data processing pipeline."""
    print("Testing data processing...")
    
    # Check if data directories exist
    regulatory_dir = os.path.join("data", "regulatory")
    pharmacovigilance_dir = os.path.join("data", "pharmacovigilance")
    veterinary_medicines_dir = os.path.join("data", "Veterinary_Medicines")
    biological_products_dir = os.path.join("data", "Biological_Products_and_Quality_Control")

    if not os.path.exists(regulatory_dir) or not os.path.exists(pharmacovigilance_dir) or not os.path.exists(veterinary_medicines_dir) or not os.path.exists(biological_products_dir):
        print(f"Error: Data directories not found. Please create {regulatory_dir}, {pharmacovigilance_dir}, {veterinary_medicines_dir}, and {biological_products_dir}")
        print("and add PDF documents before running this test.")
        return False

    # Check if there are PDF files
    regulatory_pdfs = [f for f in os.listdir(regulatory_dir) if f.lower().endswith('.pdf')]
    pharmacovigilance_pdfs = [f for f in os.listdir(pharmacovigilance_dir) if f.lower().endswith('.pdf')]
    veterinary_medicines_pdfs = [f for f in os.listdir(veterinary_medicines_dir) if f.lower().endswith('.pdf')]
    biological_products_pdfs = [f for f in os.listdir(biological_products_dir) if f.lower().endswith('.pdf')]

    if not regulatory_pdfs and not pharmacovigilance_pdfs and not veterinary_medicines_pdfs and not biological_products_pdfs:
        print("Error: No PDF files found in data directories.")
        print("Please add PDF documents before running this test.")
        return False
    
    # Initialize data processor
    processor = DataProcessor()
    
    # Process documents
    success = processor.process_all_documents()
    
    if not success:
        print("Error: Data processing failed.")
        return False
    
    print("Data processing completed successfully.")
    return True

def test_search_engine():
    """Test the search engine functionality."""
    print("\nTesting search engine...")
    
    # Check if processed data exists
    processed_data_dir = "web/processed_data"
    required_files = [
        os.path.join(processed_data_dir, "faiss_index.bin"),
        os.path.join(processed_data_dir, "chunks_data.csv"),
        os.path.join(processed_data_dir, "tfidf_vectorizer.pkl"),
        os.path.join(processed_data_dir, "tfidf_matrix.pkl")
    ]
    
    for file_path in required_files:
        if not os.path.exists(file_path):
            print(f"Error: Required file {file_path} not found.")
            print("Please run data processing first.")
            return False
    
    # Initialize search engine
    search_engine = ImprovedSearchEngine()
    
    # Test initialization
    if not search_engine.is_initialized():
        search_engine.initialize()
        if not search_engine.is_initialized():
            print("Error: Search engine initialization failed.")
            return False
    
    # Test search functionality
    test_queries = [
        ("What are the requirements for drug registration?", "regulatory"),
        ("How to report adverse events?", "pharmacovigilance"),
        ("What are the requirements for veterinary medicines?", "Veterinary_Medicines"),
        ("What are the guidelines for biological products?", "Biological_Products_and_Quality_Control"),
        ("What is the role of QPPV?", "all")
    ]
    
    for query, category in test_queries:
        print(f"\nTesting search with query: '{query}' (Category: {category})")
        results = search_engine.search(query, category)
        
        if not results:
            print(f"Warning: No results found for query '{query}' in category '{category}'.")
        else:
            print(f"Found {len(results)} results.")
            print("Top result:")
            print(f"- Document: {results[0].document}")
            print(f"- Category: {results[0].category}")
            print(f"- Score: {results[0].score}")
            print(f"- Text snippet: {results[0].text[:100]}...")
    
    print("\nSearch engine test completed.")
    return True

def main():
    """Run all tests."""
    print("=== SFDA Regulatory Chatbot Tests ===\n")
    
    # Test data processing if requested
    if len(sys.argv) > 1 and sys.argv[1] == "--process":
        if not test_data_processing():
            print("\nTest failed: Data processing encountered errors.")
            return
    
    # Test search engine
    if not test_search_engine():
        print("\nTest failed: Search engine encountered errors.")
        return
    
    print("\nAll tests completed successfully!")

if __name__ == "__main__":
    main()
