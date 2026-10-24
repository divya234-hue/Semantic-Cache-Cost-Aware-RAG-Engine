import { AlertCircle, CheckCircle2, FileText } from 'lucide-react'
import type { AskResponse } from '../api'

interface AnswerCardProps {
  result: AskResponse
}

export function AnswerCard({ result }: AnswerCardProps) {
  const supported = result.status === 'supported'

  return (
    <section className="answer-card" aria-live="polite">
      <div className={`answer-card__status ${supported ? 'is-supported' : 'is-insufficient'}`}>
        {supported ? <CheckCircle2 size={17} /> : <AlertCircle size={17} />}
        <span>{supported ? 'Evidence found' : 'Not enough evidence'}</span>
        <span className="provider-badge">
          Provider · {result.provider}
          {result.model ? ` · ${result.model}` : ''}
          {result.cache_hit ? ' · semantic cache' : ''}
        </span>
      </div>
      <p className="answer-card__text">{result.answer}</p>
      <p className="answer-card__metadata">
        Route · {result.route}
        {result.escalated ? ' · escalated' : ''}
        {' · Cost '}
        {new Intl.NumberFormat(undefined, {
          style: 'currency',
          currency: 'USD',
          maximumFractionDigits: 6,
        }).format(result.cost_usd)}
        {' · Tokens '}
        {result.input_tokens.toLocaleString()} in / {result.output_tokens.toLocaleString()} out
      </p>

      {result.citations.length > 0 ? (
        <div className="citation-list">
          <h3>Sources</h3>
          {result.citations.map((citation) => (
            <article className="citation" key={citation.chunk_id}>
              <span className="citation__icon" aria-hidden="true">
                <FileText size={16} />
              </span>
              <div className="citation__content">
                <strong>{citation.source_path}</strong>
                <small>
                  Chunk {citation.chunk_id.slice(0, 8)} · retrieval score{' '}
                  {citation.retrieval_score.toFixed(3)}
                </small>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <p className="answer-card__empty-source">No citations were returned for this response.</p>
      )}
    </section>
  )
}
