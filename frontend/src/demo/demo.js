// Demo product used before/without the backend. The numbers are the output of
// the real analysis pipeline (backend/app/nlp) run on synthetic reviews from
// backend/data/sample/demo_kestrel_orbit_5g.csv. Rebuild with
// backend/scripts/build_demo_snapshot.py. Replaced by live API data in Phase 5.
import demoAnalysis from './demoAnalysis.json'

export const DEMO_ID = 'demo'
export { demoAnalysis }

export const demoProductSummary = {
  id: DEMO_ID,
  name: demoAnalysis.product.name,
  brand: demoAnalysis.product.brand,
  category: demoAnalysis.product.category,
  source: 'demo',
  totalReviews: demoAnalysis.stats.totalReviews,
  averageRating: demoAnalysis.stats.averageRating,
  positivePercent: demoAnalysis.stats.sentimentPercent.positive,
  analyzedAt: demoAnalysis.analyzedAt,
}
