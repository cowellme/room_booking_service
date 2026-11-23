import { useCallback, useEffect, useState } from "react";
import {
  CalendarDays,
  Eye,
  History,
  MapPin,
  MessageSquare,
  Send,
  Users,
  X,
} from "lucide-react";
import { AttachmentList } from "./BookingAttachments";
import "./observedBookings.css";

const STATUS = {
  pending: "На модерации",
  in_progress: "Принята в работу",
  approved: "Подтверждена",
  rejected: "Отклонена",
  cancelled: "Отменена",
  completed: "Состоялась",
  archived: "В архиве",
};

const date = (value) =>
  value
    ? new Date(`${value}T00:00:00`).toLocaleDateString("ru-RU", {
        day: "numeric",
        month: "long",
        year: "numeric",
      })
    : "—";

const moment = (value) =>
  value ? new Date(value).toLocaleString("ru-RU", { hour12: false }) : "—";

export default function ObservedBookings({ request }) {
  const [items, setItems] = useState([]);
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [comment, setComment] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems(await request("/api/me/observed-bookings"));
    } finally {
      setLoading(false);
    }
  }, [request]);

  useEffect(() => {
    load();
  }, [load]);

  const open = async (id) => {
    setError("");
    setDetail(await request(`/api/me/observed-bookings/${id}`));
  };

  const submit = async (event) => {
    event.preventDefault();
    if (!comment.trim()) return;
    setBusy(true);
    setError("");
    try {
      await request(`/api/me/observed-bookings/${detail.id}/comments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: comment.trim() }),
      });
      setComment("");
      await open(detail.id);
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="observed-bookings">
      <header>
        <div>
          <h2>Наблюдаемые заявки</h2>
          <p>
            Заявки, к которым администратор предоставил вам доступ для
            просмотра и обсуждения.
          </p>
        </div>
        <span>{items.length}</span>
      </header>
      {loading ? (
        <div className="observed-empty">Загрузка…</div>
      ) : items.length ? (
        <div className="observed-list">
          {items.map((item) => (
            <button key={item.id} type="button" onClick={() => open(item.id)}>
              <em className={`observed-status status-${item.status}`}>
                {STATUS[item.status] || item.status}
              </em>
              <span className="observed-title">
                <b>{item.title}</b>
                <small>Номер заявки: {item.external_reference || item.id}</small>
              </span>
              <span><CalendarDays />{date(item.date_start || item.date)}</span>
              <span><MapPin />{item.building} · ауд. {item.room_number}</span>
              <Eye />
            </button>
          ))}
        </div>
      ) : (
        <div className="observed-empty">
          <Eye />
          <b>Наблюдаемых заявок пока нет</b>
          <span>Назначенные администратором заявки появятся здесь.</span>
        </div>
      )}

      {detail && (
        <div className="observed-overlay" role="dialog" aria-modal="true">
          <button className="observed-backdrop" onClick={() => setDetail(null)} aria-label="Закрыть" />
          <article className="observed-detail">
            <header>
              <div>
                <small>НАБЛЮДАЕМАЯ ЗАЯВКА</small>
                <h2>{detail.title}</h2>
                <em className={`observed-status status-${detail.status}`}>
                  {STATUS[detail.status] || detail.status}
                </em>
              </div>
              <button type="button" onClick={() => setDetail(null)} aria-label="Закрыть"><X /></button>
            </header>
            <div className="observed-scroll">
              <section className="observed-facts">
                <div><CalendarDays /><span><small>Период</small><b>{date(detail.date_start || detail.date)} — {date(detail.date_end || detail.date)}</b></span></div>
                <div><MapPin /><span><small>Аудитория</small><b>{detail.building} · {detail.room_number}</b></span></div>
                <div><Users /><span><small>Ответственный</small><b>{detail.customer_name || detail.booked_by || "—"}</b></span></div>
                <div><Users /><span><small>Подразделение</small><b>{detail.department_name || "—"}</b></span></div>
              </section>
              <section className="observed-fields">
                <p><span>Номер заявки</span><b>{detail.external_reference || detail.id}</b></p>
                <p><span>Количество участников</span><b>{detail.participants || "—"}</b></p>
                <p><span>Контакт</span><b>{detail.customer_contact || "—"}</b></p>
                {detail.comment && <p><span>Комментарий</span><b>{detail.comment}</b></p>}
              </section>
              <AttachmentList title="Файлы заявки" items={detail.attachments || []} request={request} user={{ role: "user" }} />
              <section className="observed-history">
                <h3><History />Путь заявки</h3>
                {(detail.events || []).map((entry) => (
                  <div key={entry.id}>
                    <i />
                    <span><b>{entry.summary}</b><small>{entry.actor || "Система"} · {moment(entry.created_at)}</small></span>
                  </div>
                ))}
              </section>
              <section className="observed-comments">
                <h3><MessageSquare />Комментарии</h3>
                <div>
                  {(detail.comments || []).map((entry) => (
                    <article key={entry.id}><b>{entry.author}</b><time>{moment(entry.created_at)}</time><p>{entry.text}</p></article>
                  ))}
                  {!detail.comments?.length && <span>Комментариев пока нет.</span>}
                </div>
                <form onSubmit={submit}>
                  <textarea value={comment} onChange={(event) => setComment(event.target.value)} required minLength="2" placeholder="Напишите комментарий к заявке" />
                  <button className="primary" disabled={busy}><Send />{busy ? "Отправляем…" : "Отправить"}</button>
                </form>
                {error && <p className="error">{error}</p>}
              </section>
            </div>
          </article>
        </div>
      )}
    </section>
  );
}
