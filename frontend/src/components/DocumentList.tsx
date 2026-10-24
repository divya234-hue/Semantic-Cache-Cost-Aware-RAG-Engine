import { FileText, RefreshCw, UploadCloud } from 'lucide-react'
import { useRef } from 'react'
import type { ChangeEvent } from 'react'
import type { DocumentInfo } from '../api'

interface DocumentListProps {
  documents: DocumentInfo[]
  loading: boolean
  error: string | null
  refreshing: boolean
  uploading: boolean
  uploadMessage: string | null
  uploadError: string | null
  onRefresh: () => void
  onUpload: (file: File) => void
}

function formatFileSize(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

export function DocumentList({
  documents,
  loading,
  error,
  refreshing,
  uploading,
  uploadMessage,
  uploadError,
  onRefresh,
  onUpload,
}: DocumentListProps) {
  const fileInput = useRef<HTMLInputElement>(null)

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0]
    if (file) onUpload(file)
    event.currentTarget.value = ''
  }

  return (
    <section className="panel document-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Corpus</p>
          <h2>Documents</h2>
          <p className="panel-description">Manage local TXT and PDF sources for your knowledge base.</p>
        </div>
        <button
          className="icon-button"
          type="button"
          onClick={onRefresh}
          disabled={refreshing || uploading}
          aria-label="Refresh documents and metrics"
          title="Refresh"
        >
          <RefreshCw size={17} className={refreshing ? 'spin' : ''} />
        </button>
      </div>

      <div className="upload-box">
        <span className="upload-box__icon" aria-hidden="true">
          <UploadCloud size={22} />
        </span>
        <div className="upload-box__copy">
          <strong>{uploading ? 'Uploading and indexing…' : 'Add a document'}</strong>
          <span>PDF or TXT · stored in your local corpus folder</span>
        </div>
        <button
          className="button button--primary"
          type="button"
          onClick={() => fileInput.current?.click()}
          disabled={uploading}
        >
          <UploadCloud size={16} />
          {uploading ? 'Working…' : 'Choose file'}
        </button>
        <input
          ref={fileInput}
          className="visually-hidden"
          type="file"
          accept=".txt,.pdf,text/plain,application/pdf"
          onChange={handleFileChange}
          aria-label="Choose a TXT or PDF file"
        />
      </div>

      {uploadMessage && (
        <div className="notice notice--success" role="status">
          {uploadMessage}
        </div>
      )}
      {uploadError && (
        <div className="notice notice--error" role="alert">
          {uploadError}
        </div>
      )}
      {error && (
        <div className="notice notice--error" role="alert">
          {error}
        </div>
      )}

      <div className="document-list__heading">
        <span>File</span>
        <span>Size</span>
        <span>Last modified</span>
      </div>

      {loading ? (
        <div className="state-card" role="status">
          <span className="loader" />
          Loading documents…
        </div>
      ) : error && documents.length === 0 ? (
        <div className="state-card">Document list is unavailable until the API responds.</div>
      ) : documents.length === 0 ? (
        <div className="state-card state-card--empty">
          <span className="empty-icon" aria-hidden="true">
            <FileText size={22} />
          </span>
          <strong>No documents yet</strong>
          <span>Upload a TXT or PDF file to start building your local corpus.</span>
        </div>
      ) : (
        <ul className="document-list">
          {documents.map((document) => (
            <li className="document-row" key={document.path}>
              <span className="document-row__name">
                <span className="file-icon" aria-hidden="true">
                  <FileText size={17} />
                </span>
                <span className="document-row__text">
                  <strong title={document.name}>{document.name}</strong>
                  <small>{document.extension.replace('.', '').toUpperCase()}</small>
                </span>
              </span>
              <span className="document-row__meta">{formatFileSize(document.size_bytes)}</span>
              <span className="document-row__meta">{document.modified_at}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
