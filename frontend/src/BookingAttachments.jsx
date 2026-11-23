import { useEffect, useRef, useState } from "react";
import { Download, ExternalLink, FileText, Image as ImageIcon, Paperclip, Trash2, X } from "lucide-react";
import "./attachments.css";

// Must match backend/app/services/attachments.py.
export const ATTACHMENT_EXTENSIONS = [
  "pdf", "png", "jpg", "jpeg", "gif", "webp", "txt", "csv", "rtf",
  "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "odp", "zip",
];
export const MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024;
export const MAX_ATTACHMENTS = 10;
const ACCEPT = ATTACHMENT_EXTENSIONS.map((ext) => `.${ext}`).join(",");
const IMAGE_EXTENSIONS = ["png", "jpg", "jpeg", "gif", "webp"];

const extensionOf = (name) => (String(name).includes(".") ? String(name).split(".").pop().toLowerCase() : "");
export const formatFileSize = (bytes) =>
  bytes >= 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1).replace(".", ",")} МБ`
    : `${Math.max(1, Math.round(bytes / 1024))} КБ`;
const fileProblem = (file) =>
  !ATTACHMENT_EXTENSIONS.includes(extensionOf(file.name))
    ? "этот тип файла нельзя прикрепить"
    : file.size > MAX_ATTACHMENT_BYTES
      ? "файл больше 20 МБ"
      : !file.size
        ? "файл пустой"
        : "";

// Sends the files one by one after the booking (or series) has been created.
// Returns the names that could not be uploaded, with the reason.
export async function uploadAttachments(request, target, files) {
  const url = target.seriesId
    ? `/api/booking-series/${encodeURIComponent(target.seriesId)}/attachments`
    : `/api/bookings/${target.bookingId}/attachments`;
  const failed = [];
  for (const file of files) {
    try {
      await request(url, {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream", "X-File-Name": encodeURIComponent(file.name) },
        body: file,
      });
    } catch (error) {
      failed.push(`${file.name}: ${error.message}`);
    }
  }
  return failed;
}

export const uploadFailureNotice = (failed) =>
  failed.length ? ` Не удалось прикрепить файлы: ${failed.join("; ")}` : "";

export function submitRequestWithFile(request, booking, file, series=false) {
  if(!file)throw new Error('Прикрепите файл с обоснованием заявки');
  const metadata=new TextEncoder().encode(JSON.stringify({booking,name:encodeURIComponent(file.name)}));
  const length=new Uint8Array(4);
  new DataView(length.buffer).setUint32(0,metadata.length);
  return request('/api/me/request-with-file'+(series?'?series=true':''),{
    method:'POST',headers:{'Content-Type':'application/octet-stream'},
    body:new Blob([length,metadata,file]),
  });
}

export function FileReplacementHistory({entries}) {
  const changes=[...new Map(entries.flatMap(item=>item.file_replacements||[]).map(event=>[event.replacement_id||event.id,event])).values()]
    .sort((a,b)=>a.at.localeCompare(b.at));
  if(!changes.length)return null;
  return <details className="attachment-box compact"><summary>Путь заявки</summary><ul>
    {changes.map(event=><li key={event.id}><b>Файл заменён</b> · {event.actor||'Сотрудник'} · <time dateTime={event.at}>{new Date(event.at).toLocaleString('ru-RU',{timeZone:'Europe/Moscow',hour12:false})}</time><br/>{event.before} → {event.after}</li>)}
  </ul></details>;
}

function FileIcon({ name }) {
  return IMAGE_EXTENSIONS.includes(extensionOf(name)) ? <ImageIcon /> : <FileText />;
}

const previewType=(name)=>IMAGE_EXTENSIONS.includes(extensionOf(name))?'image':extensionOf(name)==='pdf'?'pdf':null;
function StoredPreview({item}) {
  const type=previewType(item.name);
  if(!type)return <span className="attachment-preview fallback"><FileIcon name={item.name}/></span>;
  const url=item.url+(item.url.includes('?')?'&':'?')+'preview=1';
  return <a className="attachment-preview" href={item.url} target="_blank" rel="noopener" aria-label={`Открыть ${item.name}`}>
    {type==='image'?<img src={url} alt={`Предпросмотр ${item.name}`} loading="lazy"/>:<iframe src={`${url}#page=1&view=FitH&toolbar=0&navpanes=0`} title={`Первая страница ${item.name}`} loading="lazy" tabIndex="-1"/>}
  </a>;
}
function LocalPreview({file}) {
  const type=previewType(file.name);const [url,setUrl]=useState('');
  useEffect(()=>{if(!type)return;const value=URL.createObjectURL(file);setUrl(value);return()=>URL.revokeObjectURL(value)},[file,type]);
  if(!type||!url)return <span className="attachment-preview fallback"><FileIcon name={file.name}/></span>;
  return <span className="attachment-preview">{type==='image'?<img src={url} alt={`Предпросмотр ${file.name}`}/>:<iframe src={`${url}#page=1&view=FitH&toolbar=0&navpanes=0`} title={`Первая страница ${file.name}`} tabIndex="-1"/>}</span>;
}

// File chooser for the booking forms. Files are kept in the form until it is sent.
export function AttachmentPicker({ files, onChange, className = "full", hint, single=false }) {
  const inputRef = useRef(null);
  const [error, setError] = useState("");
  const add = (list) => {
    const chosen = [...list];
    const problems = chosen.map((file) => [file, fileProblem(file)]).filter(([, problem]) => problem);
    const good = chosen.filter((file) => !fileProblem(file) && !files.some((f) => f.name === file.name && f.size === file.size));
    const next = single ? (good.length ? good.slice(0,1) : files) : [...files, ...good].slice(0, MAX_ATTACHMENTS);
    const messages = problems.map(([file, problem]) => `${file.name} — ${problem}`);
    if (files.length + good.length > MAX_ATTACHMENTS) messages.push(`можно прикрепить не более ${MAX_ATTACHMENTS} файлов`);
    setError(messages.join("; "));
    onChange(next);
  };
  return (
    <div className={`${className} attachment-picker`}>
      <span>{single?'Файл к заявке *':'Файлы к заявке'}</span>
      <div
        className="attachment-drop"
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault();
          add(event.dataTransfer.files);
        }}
      >
        <button type="button" className="secondary" onClick={() => inputRef.current?.click()}>
          <Paperclip />
          {single?'Прикрепить файл':'Прикрепить файлы'}
        </button>
        <small>{hint || (single?'Приложите обоснование заявки. Один файл до 20 МБ.':'Программа, список участников, схема рассадки и т. п. До 10 файлов, каждый до 20 МБ.')}</small>
        <input
          ref={inputRef}
          type="file"
          multiple={!single}
          accept={ACCEPT}
          hidden
          onChange={(event) => {
            add(event.target.files);
            event.target.value = "";
          }}
        />
      </div>
      {files.length > 0 && (
        <ul className="attachment-list attachment-gallery">
          {files.map((file, index) => (
            <li key={`${file.name}-${file.size}-${index}`}>
              <LocalPreview file={file}/>
              <span>
                <b title={file.name}>{file.name}</b>
                <small>{formatFileSize(file.size)}</small>
              </span>
              <button
                type="button"
                className="icon"
                aria-label={`Убрать ${file.name}`}
                onClick={() => onChange(files.filter((_, i) => i !== index))}
              >
                <X />
              </button>
            </li>
          ))}
        </ul>
      )}
      {error && <p className="attachment-error">{error}</p>}
    </div>
  );
}

// Files of a booking or request card: open in a new tab, download, and (optionally) add or delete.
export function AttachmentList({ items = [], request, user, uploadTarget, onChanged, title = "Файлы", compact = false, replace=false }) {
  const inputRef = useRef(null);
  const replacementRef = useRef(null);
  const replacementId = useRef(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!items.length && !uploadTarget) return null;
  const addFiles = async (list) => {
    const chosen = [...list];
    const problems = chosen.filter(fileProblem).map((file) => `${file.name} — ${fileProblem(file)}`);
    const good = chosen.filter((file) => !fileProblem(file));
    setBusy(true);
    const failed = good.length ? await uploadAttachments(request, uploadTarget, good) : [];
    setBusy(false);
    setError([...problems, ...failed].join("; "));
    if (good.length > failed.length) await onChanged?.();
  };
  const remove = async (item) => {
    if (!window.confirm(`Удалить файл «${item.name}»?`)) return;
    try {
      await request(`/api/attachments/${item.id}`, { method: "DELETE" });
      setError("");
      await onChanged?.();
    } catch (failure) {
      setError(failure.message);
    }
  };
  const canDelete = () => user?.role === "admin";
  const replaceFile = async file => {
    if(!file||!replacementId.current)return;
    if(fileProblem(file)){setError(fileProblem(file));return}
    setBusy(true);setError('');
    try {
      await request(`/api/me/attachments/${replacementId.current}`,{method:'PUT',headers:{'Content-Type':'application/octet-stream','X-File-Name':encodeURIComponent(file.name)},body:file});
      await onChanged?.();
    }catch(error){setError(error.message)}
    finally{setBusy(false)}
  };
  return (
    <section className={`attachment-box ${compact ? "compact" : ""}`}>
      <h4>
        <Paperclip />
        {title}
        {items.length > 0 && <b>{items.length}</b>}
      </h4>
      {items.length > 0 ? (
        <ul className="attachment-list attachment-gallery">
          {items.map((item) => (
            <li key={item.id}>
              <StoredPreview item={item}/>
              <span>
                <a href={item.url} target="_blank" rel="noopener" title={item.viewable ? "Открыть" : "Скачать"}>
                  {item.name}
                </a>
                <small>
                  {formatFileSize(item.size)}
                  {item.scope === "series" ? " · для всей серии" : ""}
                  {item.uploaded_by ? ` · ${item.uploaded_by}` : ""}
                </small>
              </span>
              {item.viewable && (
                <a className="icon" href={item.url} target="_blank" rel="noopener" aria-label="Открыть" title="Открыть">
                  <ExternalLink />
                </a>
              )}
              <a className="icon" href={item.download_url} aria-label="Скачать" title="Скачать">
                <Download />
              </a>
              {onChanged && canDelete(item) && (
                <button type="button" className="icon" aria-label="Удалить" title="Удалить" onClick={() => remove(item)}>
                  <Trash2 />
                </button>
              )}
              {replace&&<button type="button" className="secondary" disabled={busy} onClick={()=>{replacementId.current=item.id;replacementRef.current?.click()}}>{busy?'Сохраняем…':'Заменить файл'}</button>}
            </li>
          ))}
        </ul>
      ) : (
        <p className="attachment-empty">Файлы не прикреплены</p>
      )}
      {uploadTarget && (
        <>
          <button type="button" className="secondary attachment-add" disabled={busy} onClick={() => inputRef.current?.click()}>
            <Paperclip />
            {busy ? "Загружаем…" : "Добавить файл"}
          </button>
          <input
            ref={inputRef}
            type="file"
            multiple
            accept={ACCEPT}
            hidden
            onChange={(event) => {
              addFiles(event.target.files);
              event.target.value = "";
            }}
          />
        </>
      )}
      {replace&&<input ref={replacementRef} type="file" accept={ACCEPT} hidden onChange={e=>{const file=e.target.files?.[0];e.target.value='';replaceFile(file)}}/>}
      {error && <p className="attachment-error">{error}</p>}
    </section>
  );
}
