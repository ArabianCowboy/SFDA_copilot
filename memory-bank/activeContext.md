# SFDA Copilot - Active Context

## Current Focus
- Optimizing hybrid search performance
- Expanding pharmacovigilance term dictionary
- Improving query expansion logic
- Enhancing response accuracy from OpenAI

## Recent Changes
2024-04-26:
- Implemented local sentence-transformers embeddings
- Added query preprocessing with pharma-specific terms
- Improved FAISS index initialization
- Updated security headers configuration

## Ongoing Work
1. **Search Engine Improvements**
   - Testing different weight combinations
   - Evaluating candidate multipliers
   - Benchmarking performance

2. **UI Enhancements**
   - Mobile responsive sidebar
   - Loading state indicators
   - Accessibility improvements

3. **Documentation**
   - Maintaining knowledge base
   - Updating technical documentation
   - Creating user guides

## Key Decisions
- Using local embeddings instead of OpenAI to:
  - Reduce API costs
  - Improve domain specificity
  - Maintain privacy

- Chose hybrid search approach to:
  - Combine semantic understanding
  - Preserve keyword matching
  - Get best of both methods

## Next Steps
1. Refine query expansion dictionary
2. Add more test cases for edge scenarios
3. Document search performance benchmarks
4. Monitor production usage patterns
