import faiss
import os

try:
    index_path = "web/processed_data/faiss_index.bin"
    if os.path.exists(index_path):
        print("Loading FAISS index...")
        index = faiss.read_index(index_path)
        print(f"Successfully loaded FAISS index with {index.ntotal} vectors")
    else:
        print("FAISS index file not found")
except Exception as e:
    print(f"Error loading FAISS index: {str(e)}")
