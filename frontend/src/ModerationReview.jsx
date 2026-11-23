import { useEffect, useState } from 'react';
import './moderationReview.css';
import ShortNoticeBadge from './ShortNoticeBadge';
import { BookingQuestionSummary } from './BookingQuestions';

export default function ModerationReview({ item, request, close, approve, reject, takeInWork, busy, removeExtra }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');

  const load = () => {
    setError('');
    setData(null);
    Promise.all([request('/api/admin/bookings'), request('/api/rooms')])
      .then(([pending, rooms]) => setData({ pending, rooms }))
      .catch((event) => setError(event.message));
  };

  useEffect(() => { load(); }, [item.id]);
  useEffect(() => {
    const key = (event) => {
      if (event.key === 'Escape' && !busy) close();
    };
    document.addEventListener('keydown', key);
    return () => document.removeEventListener('keydown', key);
  }, [busy, close]);

  const originals = item.series_items || [item];
  const entries = originals.map((row) => data?.pending.find((entry) => entry.id === row.id)).filter(Boolean);
  const all = entries.flatMap((row) => [row, ...data.pending.filter((entry) => entry.parent_booking_id === row.id)]);
  const roomOf = (row) => data?.rooms.find((room) => room.id === row.room_id);
  const issues = (row) => {
    const room = roomOf(row);
    return [
      row.has_conflict ? 'Пересечение с подтверждённой бронью' : null,
      !room ? 'Аудитория недоступна' : null,
      room && row.participants > Math.max(room.capacity || 0, room.max_capacity || 0) ? 'Превышена вместимость' : null,
    ].filter(Boolean);
  };
  const blocked = all.some((row) => issues(row).length);
  const complete = entries.length === originals.length;
  const fresh = {
    ...item,
    ...entries[0],
    ...(item.series_items ? { series_items: entries, series_id: item.series_id } : {}),
    set_extras: all.filter((entry) => entry.parent_booking_id),
  };

  return (
    <div className="moderation-review-overlay" onClick={(event) => { if (event.target === event.currentTarget && !busy) close(); }}>
      <section className="moderation-review" role="dialog" aria-modal="true" aria-labelledby="review-title">
        <header>
          <div>
            <small>ПРОВЕРКА ЗАЯВКИ</small>
            <h2 id="review-title">Номер заявки: {item.external_reference || 'не указан'}</h2>
            <p>{item.title}</p>
          </div>
          <button className="icon" onClick={close} disabled={busy} aria-label="Закрыть">×</button>
        </header>
        <main>
          {error ? (
            <p role="alert">{error} <button onClick={load}>Повторить проверку</button></p>
          ) : !data ? (
            <p>Проверяем актуальные данные…</p>
          ) : (
            <>
              <div className={`review-result ${blocked || !complete ? 'bad' : 'good'}`}>
                {!complete ? 'Часть заявок уже рассмотрена. Обновите список.' : blocked ? 'Есть препятствия для подтверждения' : 'Аудитория свободна, проверка вместимости пройдена'}
              </div>
              <p><b>Ответственный:</b> {item.customer_name || item.booked_by}<br /><b>Подразделение:</b> {item.department_name || 'не указано'}<br /><b>Контакт:</b> {item.customer_contact || 'не указан'}</p>
              {all.map((row) => (
                <article className="review-room" key={row.id}>
                  <h3>{row.building} · аудитория {row.room_number}</h3>
                  <p>{row.parent_booking_id ? `Дополнительная · ${row.room_purpose || ''}` : 'Основная'} · {row.date.split('-').reverse().join('.')}</p>
                  <ShortNoticeBadge item={row} />
                  <ReviewChecks row={row} room={roomOf(row)} />
                  {row.parent_booking_id && removeExtra && <button type="button" className="secondary" disabled={busy} onClick={async () => { await removeExtra(row); load(); }}>Убрать из комплекта</button>}
                  <p>Участников: {row.participants || 'не указано'} · Вместимость: {roomOf(row)?.capacity ?? '—'}{roomOf(row)?.max_capacity ? ` · Максимум: ${roomOf(row).max_capacity}` : ''}</p>
                  {issues(row).map((text) => <p className="review-bad" key={text}>{text}</p>)}
                  {row.conflict && <p>Аудитория занята на эту дату: {row.conflict.title}</p>}
                </article>
              ))}
              <div className="review-result manual">
                <b>Ручная проверка услуг</b>
                <BookingQuestionSummary item={item} />
                {typeof item.technical_support_required === 'boolean' && <p>МТО (ранее указано): {item.technical_support_required ? 'требуется' : 'не требуется'}.</p>}
                <p>{item.requested_equipment?.join(', ') || 'Дополнительное оснащение не указано'}</p>
                <p>При необходимости уточните возможность предоставления услуг у ответственных сотрудников. Автоматически эти услуги не согласованы.</p>
              </div>
              {item.comment && <blockquote>{item.comment}</blockquote>}
            </>
          )}
        </main>
        <footer>
          <button className="secondary" disabled={busy} onClick={() => { const row = entries[0] || item; window.dispatchEvent(new CustomEvent('review-calendar', { detail: row })); close(); }}>Проверить в календаре</button>
          <button className="review-reject" onClick={() => reject(fresh)} disabled={!data || !complete || busy}>Отклонить</button>
          {item.series_items && complete && entries.some((entry) => entry.has_conflict) && entries.some((entry) => !entry.has_conflict) && <button className="secondary" disabled={busy} onClick={async () => { if (!await approve(fresh, true, close)) load(); }}>Подтвердить свободные даты</button>}
          <button className="primary review-approve" disabled={!data || !complete || blocked || busy} onClick={async () => { if (!await approve(fresh, false, close)) load(); }}>{busy ? 'Сохраняем…' : 'Подтвердить'}</button>
        </footer>
      </section>
    </div>
  );
}

function ReviewChecks({ row, room }) {
  const limit = room ? Math.max(Number(room.capacity) || 0, Number(room.max_capacity) || 0) : null;
  const checks = [
    ['Аудитория', room ? 'Доступна для бронирования' : 'Недоступна', Boolean(room)],
    ['Дата', row.has_conflict ? 'Есть пересечение с бронью' : row.date.split('-').reverse().join('.'), !row.has_conflict],
    ['Вместимость', !room ? 'Нет данных' : row.participants ? `${row.participants} из ${limit} мест` : 'Количество не указано', room && row.participants ? row.participants <= limit : null],
  ];
  return <div className="review-checks">{checks.map(([title, text, ok]) => <div key={title} className={`review-check ${ok === null ? 'manual' : ok ? 'passed' : 'failed'}`}><i aria-hidden="true">{ok === null ? '!' : ok ? '✓' : '×'}</i><div><strong>{title}</strong><span>{text}</span><small>{ok === null ? 'Требует внимания' : ok ? 'Проверка пройдена' : 'Есть препятствие'}</small></div></div>)}</div>;
}
