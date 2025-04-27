from web.services.search_engine import ImprovedSearchEngine

def test_search(query, category="all"):
    se = ImprovedSearchEngine()
    se.initialize()
    
    if not se.is_initialized():
        print("Search engine failed to initialize")
        return
        
    print(f"\nTesting query: '{query}' (category: {category})")
    results = se.search(query, category=category)
    
    if not results:
        print("No results found")
        return
        
    print(f"Found {len(results)} results:")
    for i, result in enumerate(results, 1):
        print(f"\nResult {i}:")
        print(f"Document: {result.get('document')}")
        print(f"Page: {result.get('page')}")
        print(f"Category: {result.get('category')}")
        print(f"Score: {result.get('score')}")
        print(f"Text snippet: {result.get('text')[:200]}...")

if __name__ == "__main__":
    # Test with some likely queries
    test_search("clinical trials", "regulatory")
    test_search("pharmacovigilance", "pharmacovigilance")
    test_search("GMP guidelines", "all")
