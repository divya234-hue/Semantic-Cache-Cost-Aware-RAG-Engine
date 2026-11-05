import {
  FileText,
  Filter,
  RefreshCw,
  Search,
  Trash2,
  UploadCloud,
} from 'lucide-react'
import { useRef, useState } from 'react'
import type { ChangeEvent, DragEvent } from 'react'
import type { DocumentInfo } from '../api'

interface DocumentListProps {
  documents: DocumentInfo[]
  canManageDocuments: boolean
  loading: boolean
  error: string | null
  refreshing: boolean
  uploading: boolean
  uploadProgress: number | null
  uploadMessage: string | null
  uploadError: string | null
  deleteMessage: string | null
  deleteError: string | null
  deletingFilename: string | null
  reindexing: boolean
  onRefresh: () => void
  onUpload: (file: File) => void
  onDelete: (document: DocumentInfo) => void
  onReindex: () => void
}

function formatFileSize(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

export function DocumentList({
  documents,
  canManageDocuments,
  loading,
  error,
  refreshing,
  uploading,
  uploadProgress,
  uploadMessage,
  uploadError,
  deleteMessage,
  deleteError,
  deletingFilename,
  reindexing,
  onRefresh,
  onUpload,
  onDelete,
  onReindex,
}: DocumentListProps) {
  const fileInput = useRef<HTMLInputElement>(null)
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('all')
  const [dragging, setDragging] = useState(false)

  function acceptFile(file?: File) {
    if (file) onUpload(file)
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    acceptFile(event.currentTarget.files?.[0])
    event.currentTarget.value = ''
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setDragging(false)
    acceptFile(event.dataTransfer.files[0])
  }

  const filteredDocuments = documents.filter((document) => {
    const matchesSearch = document.name.toLowerCase().includes(search.trim().toLowerCase())
    const matchesType = typeFilter === 'all' || document.extension === typeFilter
    return matchesSearch && matchesType
  })

  return (
    <section className="panel document-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Knowledge base</p>
          <h2>Documents</h2>
          <p className="panel-description">
            Upload and manage PDF and UTF-8 text sources in your local corpus.
          </p>
        </div>
        <div className="panel-heading__actions">
          {canManageDocuments && (
            <button
              className="button button--secondary"
              type="button"
              onClick={onReindex}
              disabled={reindexing || uploading || documents.length === 0}
            >
              <RefreshCw size={15} className={reindexing ? 'spin' : ''} />
              {reindexing ? 'Indexing…' : 'Re-index corpus'}
            </button>
          )}
          <button
            className="icon-button"
            type="button"
            onClick={onRefresh}
            disabled={refreshing || uploading || reindexing}
            aria-label="Refresh documents and metrics"
            title="Refresh"
          >
            <RefreshCw size={17} className={refreshing ? 'spin' : ''} />
          </button>
        </div>
      </div>

      {canManageDocuments && (
        <div
          className={`upload-box ${dragging ? 'is-dragging' : ''}`}
          onDragEnter={(event) => {
            event.preventDefault()
            setDragging(true)
          }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
              setDragging(false)
            }
          }}
          onDrop={handleDrop}
        >
          <span className="upload-box__icon" aria-hidden="true">
            <UploadCloud size={22} />
          </span>
          <div className="upload-box__copy">
            <strong>{uploading ? 'Uploading document…' : 'Drop a file to add it to your corpus'}</strong>
            <span>
              {uploading && uploadProgress !== null
                ? `Upload progress · ${uploadProgress}%`
                : 'PDF or TXT · stored locally and indexed after upload'}
            </span>
            {uploading && (
              <progress
                className="upload-progress"
                max="100"
                value={uploadProgress ?? undefined}
                aria-label="Document upload progress"
              />
            )}
          </div>
          <button
            className="button button--primary"
            type="button"
            onClick={() => fileInput.current?.click()}
            disabled={uploading || reindexing}
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
      )}

      {uploadMessage && <div className="notice notice--success" role="status">{uploadMessage}</div>}
      {uploadError && <div className="notice notice--error" role="alert">{uploadError}</div>}
      {deleteMessage && <div className="notice notice--success" role="status">{deleteMessage}</div>}
      {deleteError && <div className="notice notice--error" role="alert">{deleteError}</div>}
      {error && <div className="notice notice--error" role="alert">{error}</div>}

      <div className="document-toolbar">
        <label className="search-field">
          <Search size={16} aria-hidden="true" />
          <span className="visually-hidden">Search documents</span>
          <input
            type="search"
            placeholder="Search documents"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <label className="filter-field">
          <Filter size={15} aria-hidden="true" />
          <span className="visually-hidden">Filter by file type</span>
          <select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}>
            <option value="all">All types</option>
            <option value=".pdf">PDF</option>
            <option value=".txt">TXT</option>
          </select>
        </label>
        <span className="document-result-count">
          {filteredDocuments.length} of {documents.length} files
        </span>
      </div>

      <div className="document-list__heading">
        <span>File</span>
        <span>Size</span>
        <span>Last modified</span>
        <span className="visually-hidden">Actions</span>
      </div>

      {loading ? (
        <div className="state-card" role="status"><span className="loader" />Loading documents…</div>
      ) : error && documents.length === 0 ? (
        <div className="state-card">Document list is unavailable until the API responds.</div>
      ) : documents.length === 0 ? (
        <div className="state-card state-card--empty">
          <span className="empty-icon" aria-hidden="true"><FileText size={22} /></span>
          <strong>No documents yet</strong>
          <span>Upload a TXT or PDF file to start building your local corpus.</span>
        </div>
      ) : filteredDocuments.length === 0 ? (
        <div className="state-card state-card--empty">
          <span className="empty-icon" aria-hidden="true"><Search size={21} /></span>
          <strong>No matching documents</strong>
          <span>Try a different search term or file type.</span>
        </div>
      ) : (
        <ul className="document-list">
          {filteredDocuments.map((document) => (
            <li className="document-row" key={document.path}>
              <span className="document-row__name">
                <span className="file-icon" aria-hidden="true"><FileText size={17} /></span>
                <span className="document-row__text">
                  <strong title={document.name}>{document.name}</strong>
                  <small>{document.extension.replace('.', '').toUpperCase()}</small>
                </span>
              </span>
              <span className="document-row__meta">{formatFileSize(document.size_bytes)}</span>
              <span className="document-row__meta">{document.modified_at}</span>
              {canManageDocuments && document.can_edit && (
                <button
                  className="icon-button icon-button--danger"
                  type="button"
                  onClick={() => onDelete(document)}
                  disabled={deletingFilename !== null || uploading || reindexing}
                  aria-label={`Delete ${document.name}`}
                  title="Delete document"
                >
                  {deletingFilename === document.name
                    ? <span className="loader loader--tiny" />
                    : <Trash2 size={16} />}
                </button>
              )}
              {(!canManageDocuments || !document.can_edit) && <span aria-hidden="true" />}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
