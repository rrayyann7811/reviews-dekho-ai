// How to describe the sentiment engine that produced an analysis run (analysis.engine from the API).

/** { name, method, scoreNote, outdated } for an analysis' engine record. */
export function describeEngine(engine) {
  if (engine?.id === 'transformer') {
    return {
      name: 'RoBERTa sentiment model',
      method: 'a pretrained language model (Twitter-RoBERTa by Cardiff NLP) that reads each review and each feature’s phrase',
      scoreNote: 'Each review is labelled with the model’s most likely class. The score, from −1 to +1, is the chance it is positive minus the chance it is negative.',
      outdated: false,
    }
  }
  return {
    name: 'VADER (rule-based)',
    method: 'VADER, a rule-based method that scores words from a dictionary, with extra rules for review phrases',
    scoreNote: 'Each review gets a score from −1 (very negative) to +1 (very positive). Scores between −0.05 and +0.05 count as neutral.',
    // Runs made before Phase 4 used an earlier VADER pipeline with one feature list for every product.
    outdated: !engine || (engine.pipelineVersion ?? 1) < 2,
  }
}
