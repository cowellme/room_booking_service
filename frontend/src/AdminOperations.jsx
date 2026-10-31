import {firstSeriesDate} from './seriesDates';
import BookingQuestions from './BookingQuestions';
import ExtraRoomsGuide from './ExtraRoomsGuide';
import { useEffect, useMemo, useState } from 'react';
import { AlertCircle, Ban, Building2, Check, Clock3, Search, CalendarDays, ChevronLeft, ChevronRight, Copy, Link2, MessageSquarePlus, Repeat2, ShieldCheck, Users, X } from 'lucide-react';
import { readDraft, writeStored } from './bookingCenterConfig';
import { AttachmentPicker, uploadAttachments, uploadFailureNotice } from './BookingAttachments';
import { BookingSetupNotice } from './RoomEquipmentBlock';

const iso = date => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
const addDays = (date, count) => { const value = new Date(date); value.setDate(value.getDate() + count); return value };
const monday = date => addDays(date, -((date.getDay() + 6) % 7));
const times = Array.from({ length: 29 }, (_, index) => { const value = 8 * 60 + index * 30; return `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}` });
const dateLabel = value => new Date(`${value}T00:00:00`).toLocaleDateString('ru-RU', { weekday: 'short', day: 'numeric', month: 'short' });

// Records that no longer occupy the room would hide real bookings behind the "+N" overflow.
const GRID_HIDDEN_STATUSES = new Set(['cancelled', 'cancelled_by_user', 'cancelled_by_admin', 'rejected', 'transferred']);

export function OperationalGrid({ items, rooms, openBooking, openDetail }) {
  const [mode, setMode] = useState('week'); const [cursor, setCursor] = useState(() => monday(new Date())); const [building, setBuilding] = useState(''); const [limit, setLimit] = useState(30);
  const days = Array.from({ length: mode === 'day' ? 1 : 7 }, (_, index) => addDays(cursor, index));
  const buildingOptions = [...new Map(rooms.map(room => [room.building_id, room.building])).entries()];
  const matchingRooms = rooms.filter(room => !building || String(room.building_id) === building); const activeRooms = matchingRooms.slice(0, limit);
  const move = mode === 'day' ? 1 : 7; const columns = `160px repeat(${days.length}, minmax(${mode === 'day' ? 500 : 130}px, 1fr))`;
  return <section className={`operations-grid-shell ${mode}`}><header><div><small>ОПЕРАТИВНАЯ СЕТКА</small><h2>Аудитории × {mode === 'day' ? 'время дня' : 'дни недели'}</h2></div><div className="operations-grid-filters"><select aria-label="Корпус" value={building} onChange={event => setBuilding(event.target.value)}><option value="">Все корпуса</option>{buildingOptions.map(([id, name]) => <option value={id} key={id}>{name}</option>)}</select><button className={mode === 'day' ? 'active' : ''} onClick={() => { setMode('day'); setCursor(new Date()) }}>День</button><button className={mode === 'week' ? 'active' : ''} onClick={() => { setMode('week'); setCursor(monday(cursor)) }}>Неделя</button><button onClick={() => setCursor(addDays(cursor, -move))}><ChevronLeft /></button><button onClick={() => setCursor(mode === 'day' ? new Date() : monday(new Date()))}>Сегодня</button><button onClick={() => setCursor(addDays(cursor, move))}><ChevronRight /></button></div></header><div className="operations-grid"><div className="operations-grid-head" style={{ gridTemplateColumns: columns }}><b>Аудитория</b>{days.map(day => <span className={[0, 6].includes(day.getDay()) ? 'weekend' : ''} key={iso(day)}>{day.toLocaleDateString('ru-RU', { weekday: 'short', month: 'long' })}<strong>{day.getDate()}</strong></span>)}</div>{activeRooms.map(room => <div className="operations-grid-row" style={{ gridTemplateColumns: columns }} key={room.id}><div className="operations-room"><b>Ауд. {room.number}</b><small>{room.building}</small></div>{days.map(day => { const records = items.filter(item => item.room_id === room.id && item.date === iso(day) && !item.archived_at && !GRID_HIDDEN_STATUSES.has(item.status)); return <div className="operations-cell" key={iso(day)}>{records.slice(0, mode === 'day' ? 12 : 3).map(item => <button className={`operations-entry ${item.record_kind || 'booking'} ${item.status}`} style={{ '--entry-color': item.color }} onClick={() => openDetail(item)} key={item.id}><time>{item.time_start}–{item.time_end}</time><span>{item.title}</span></button>)}{records.length > (mode === 'day' ? 12 : 3) && <small>+{records.length - (mode === 'day' ? 12 : 3)}</small>}<button className="operations-add" aria-label={`Забронировать аудиторию ${room.number} на ${dateLabel(iso(day))}`} onClick={() => openBooking({ date: iso(day), building_id: String(room.building_id), room_type: room.type || '', preferred_room_id: room.id, preferred_room: room })}>+</button></div> })}</div>)}</div>{matchingRooms.length > limit && <p className="operations-grid-note">Показано {limit} из {matchingRooms.length} аудиторий. <button type="button" className="secondary" onClick={() => setLimit(limit + 30)}>Показать ещё</button></p>}</section>
}

export function ServiceBlockDialog({ rooms, request, close, done }) { const [saving, setSaving] = useState(false); const [error, setError] = useState(''); const submit = async event => { event.preventDefault(); setSaving(true); setError(''); const data = new FormData(event.currentTarget); try { await request('/api/admin/service-blocks', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ room_ids: data.getAll('room_ids').map(Number), date: data.get('date'), date_end: data.get('date_end'), time_start: data.get('time_start'), time_end: data.get('time_end'), record_kind: data.get('record_kind'), title: data.get('title'), reason: data.get('reason') }) }); done() } catch (failure) { setError(failure.message); setSaving(false) } }; return <DialogShell title="Служебная блокировка" eyebrow="НЕДОСТУПНОСТЬ АУДИТОРИИ" close={close}><form className="operation-form" onSubmit={submit}><p>Ремонт, застройка и демонтаж будут отображаться в календаре и блокировать выбранное время.</p><label><span>Тип блокировки</span><select name="record_kind" required><option value="maintenance">Ремонт</option><option value="setup">Застройка / подготовка</option><option value="teardown">Демонтаж</option><option value="unavailable">Другая недоступность</option></select></label><label className="full"><span>Аудитории</span><select name="room_ids" multiple required size="7">{rooms.map(room => <option value={room.id} key={room.id}>Ауд. {room.number} · {room.building}</option>)}</select><small>Для выбора нескольких удерживайте Ctrl.</small></label><label><span>С даты</span><input name="date" type="date" required /></label><label><span>По дату</span><input name="date_end" type="date" required /></label><label><span>Начало</span><TimeSelect name="time_start" /></label><label><span>Окончание</span><TimeSelect name="time_end" /></label><label className="full"><span>Название</span><input name="title" required minLength="2" placeholder="Например, ремонт системы вентиляции" /></label><label className="full"><span>Причина и пояснение</span><textarea name="reason" required minLength="2" /></label>{error && <p className="error full">{error}</p>}<footer className="full"><button type="button" className="secondary" onClick={close}>Отмена</button><button className="primary" disabled={saving}><Ban />{saving ? 'Сохраняем…' : 'Создать блокировку'}</button></footer></form></DialogShell> }


// Same layout and classes as the user's "Серия бронирований" (UserBookingPortal), but the series is created already approved.
const SERIES_WEEKDAYS = [['Пн', 0], ['Вт', 1], ['Ср', 2], ['Чт', 3], ['Пт', 4], ['Сб', 5], ['Вс', 6]];
const seriesShortDate = value => new Date(`${value}T00:00:00`).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' });
const seriesLongDate = value => new Date(`${value}T00:00:00`).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' });
export function BatchBookingDialog({ rooms, departments, request, close, done, user, initialRoomIds = [], draftKey, draftToken }) {
  const [draft] = useState(() => readDraft(draftKey, draftToken));
  const [form, setForm] = useState(() => draft?.form || { date: '', date_end: '', time_start: '', time_end: '', participants: '', building_id: '', title: '', customer_name: user?.full_name || '', department_id: '', customer_contact: '', external_channel: '', external_reference: '', external_url: '', comment: '', catering: '' });
  const [weekdays, setWeekdays] = useState(draft?.weekdays || [0, 1, 2, 3, 4]);
  const [selectedIds, setSelectedIds] = useState(draft?.selectedIds || initialRoomIds.map(Number));
  useEffect(() => { if (draftKey) writeStored(draftKey, { token: draftToken, form, weekdays, selectedIds }); }, [form, weekdays, selectedIds]);
  const [leadError, setLeadError] = useState('');
  const [availability, setAvailability] = useState(null);
  const [busy, setBusy] = useState({});
  const [checking, setChecking] = useState(false);
  const [attempted, setAttempted] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const update = (key, value) => { if (key === 'date') { setLeadError(''); setError(''); } setForm(current => ({ ...current, [key]: value })); };
  const buildings = useMemo(() => [...new Map(rooms.map(room => [room.building_id, room.building])).entries()].sort((a, b) => String(a[1]).localeCompare(String(b[1]), 'ru')), [rooms]);
  const firstOccurrence = firstSeriesDate(form.date, form.date_end, weekdays);
  const searchReady = Boolean(form.date && form.time_start && form.time_end && form.time_start < form.time_end && Number(form.participants) > 0);
  const periodReady = Boolean(form.date_end && form.date_end >= form.date && weekdays.length);
  const requiredReady = Boolean(form.catering && form.technical_support && searchReady && periodReady && form.title.trim().length >= 2 && form.customer_name.trim().length >= 2 && (!form.customer_contact.trim() || form.customer_contact.trim().length >= 3) && (form.external_reference || '').trim().length > 0 && form.department_id);
  const mark = ok => ok ? 'complete' : attempted ? 'invalid' : '';
  useEffect(() => {
    setLeadError('');
    if (!searchReady || !firstOccurrence) { setAvailability(null); return; }
    let active = true;
    const timer = setTimeout(async () => {
      setChecking(true);
      try {
        const result = await request('/api/admin/availability', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ date: firstOccurrence, time_start: form.time_start, time_end: form.time_end, participants: Number(form.participants), building_id: form.building_id ? Number(form.building_id) : null, equipment: [] }) });
        if (active) setAvailability(result);
      } catch (failure) { if (active) { setAvailability(null); if (failure.message.includes('7 рабочих дней')) setLeadError(failure.message); else setError(failure.message); } }
      finally { if (active) setChecking(false); }
    }, 450);
    return () => { active = false; clearTimeout(timer); };
  }, [firstOccurrence, form.date, form.time_start, form.time_end, form.participants, form.building_id, searchReady]);
  useEffect(() => {
    if (!searchReady || !periodReady) { setBusy({}); return; }
    let active = true;
    const timer = setTimeout(() => request('/api/booking-series/availability', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ date: form.date, date_end: form.date_end, time_start: form.time_start, time_end: form.time_end, weekdays }) })
      .then(data => active && setBusy(data.busy || {})).catch(() => active && setBusy({})), 300);
    return () => { active = false; clearTimeout(timer); };
  }, [form.date, form.date_end, form.time_start, form.time_end, weekdays.join('|'), searchReady, periodReady]);
  const busyDates = room => busy[String(room.id)] || [];
  const isSelected = room => selectedIds.includes(room.id);
  const candidates = rooms.filter(room => (!form.building_id || String(room.building_id) === form.building_id)  && (!Number(form.participants) || room.capacity >= Number(form.participants)));
  const shown = availability ? availability.free : candidates;
  const selectedRooms = rooms.filter(isSelected);
  const toggleDay = day => setWeekdays(current => current.includes(day) ? current.filter(item => item !== day) : [...current, day]);
  const toggleRoom = room => {
    if (!availability) return;
    if (!isSelected(room) && busyDates(room).length) return;
    setSelectedIds(current => current.includes(room.id) ? current.filter(id => id !== room.id) : [...current, room.id]);
  };
  const [files, setFiles] = useState([]);
  const submit = async () => {
    setAttempted(true); setError('');
    if (!requiredReady || !selectedRooms.length) { setError('Заполните период, время, участников, название, ФИО, подразделение, номер заявки и выберите хотя бы одну аудиторию'); return; }
    const blocked = selectedRooms.find(room => busyDates(room).length);
    if (blocked) { setError(`Аудитория ${blocked.number} занята в часть дат серии — снимите её или измените период`); return; }
    setSaving(true);
    try {
      const result = await request('/api/admin/booking-series', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ room_ids: selectedRooms.map(room => room.id), date: form.date, date_end: form.date_end, weekdays, time_start: form.time_start, time_end: form.time_end, title: form.title.trim(), booking_type: 'other', participants: Number(form.participants), customer_name: form.customer_name.trim(), customer_contact: form.customer_contact.trim() || null, department_id: Number(form.department_id), external_reference: (form.external_reference || '').trim(), comment: form.comment.trim() || null, catering_required: form.catering === 'yes', technical_support_required: form.technical_support === 'yes', requested_equipment: [] }) });
      const failed = result.series_id ? await uploadAttachments(request, { seriesId: result.series_id }, files) : [];
      done(`Создано бронирований: ${result.created}.${uploadFailureNotice(failed)}`);
    } catch (failure) { if (failure.message.includes('7 рабочих дней')) setLeadError(failure.message); else setError(failure.message); setSaving(false); }
  };
  return <div className="admin-series-overlay" role="dialog" aria-modal="true" onClick={event=>{if(event.target===event.currentTarget&&!saving)close()}}><div className="user-booking-portal admin-series-portal"><div className={`user-request-layout has-matches series-modal-mode`}>
    <div className="series-modal-banner"><div><small>НЕСКОЛЬКО ДАТ И АУДИТОРИЙ</small><h2>Серия бронирований</h2><p>Бронирования серии будут сразу подтверждены и появятся в календаре</p></div><button type="button" className="icon" onClick={close}>Закрыть</button></div>
    <section className="user-request-form"><header><span>1</span><div><h2>Параметры серии</h2><p>Укажите период и время — справа появятся свободные аудитории.</p></div></header>
      <div className="user-request-fields">
        <label className={leadError?'invalid lead-date-invalid':mark(form.date)}><span>Дата начала серии *</span><input type="date" lang="ru-RU" min={iso(new Date())} value={form.date} onChange={event => update('date', event.target.value)} />{leadError&&<small className="booking-lead-warning" role="alert">{leadError}</small>}</label>
        <label className={mark(form.date_end && form.date_end >= form.date)}><span>Дата окончания серии *</span><input type="date" lang="ru-RU" min={form.date || iso(new Date())} value={form.date_end} onChange={event => update('date_end', event.target.value)} /></label>
        <div className={`series-fields full ${attempted&&!weekdays.length?'invalid':''}`}><div><span>Дни повторения *</span><div className="series-weekdays">{SERIES_WEEKDAYS.map(([name, day]) => <button type="button" className={weekdays.includes(day) ? 'active' : ''} onClick={() => toggleDay(day)} key={day}>{name}</button>)}</div></div><p className="series-hint">Выберите аудитории справа — бронирования создаются на каждый выбранный день в каждой аудитории.</p></div>
        <label className={mark(form.time_start)}><span>Начало *</span><select value={form.time_start} onChange={event => update('time_start', event.target.value)}><option value="">Выберите время</option>{times.map(value => <option key={value}>{value}</option>)}</select></label>
        <label className={mark(form.time_end && form.time_end > form.time_start)}><span>Окончание *</span><select value={form.time_end} onChange={event => update('time_end', event.target.value)}><option value="">Выберите время</option>{times.map(value => <option key={value}>{value}</option>)}</select></label>
        <label className={mark(Number(form.participants) > 0)}><span>Количество участников *</span><input type="number" min="1" max="5000" value={form.participants} onChange={event => update('participants', event.target.value)} placeholder="Например, 25" /></label>
        <label><span>Корпус</span><select value={form.building_id} onChange={event => update('building_id', event.target.value)}><option value="">Любой корпус</option>{buildings.map(([id, name]) => <option value={id} key={id}>{name}</option>)}</select></label>
        
        <label className={`full ${mark(form.title.trim().length >= 2)}`}><span>Название программы или мероприятия *</span><input value={form.title} onChange={event => update('title', event.target.value)} placeholder="Например, курс повышения квалификации" /></label>
        <label className={mark(form.customer_name.trim().length >= 2)}><span>ФИО ответственного *</span><input value={form.customer_name} onChange={event => update('customer_name', event.target.value)} placeholder="Иванова Анна Сергеевна" /></label>
        <label className={mark(form.department_id)}><span>Подразделение *</span><select value={form.department_id} onChange={event => update('department_id', event.target.value)}><option value="">Выберите подразделение</option>{departments.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
        <label className={mark((form.external_reference || '').trim().length > 0)}><span>Номер заявки *</span><input value={form.external_reference || ''} onChange={event => update('external_reference', event.target.value)} maxLength={120} placeholder="Введите номер заявки" /></label>
        <label className={mark(!form.customer_contact.trim() || form.customer_contact.trim().length >= 3)}><span>Телефон</span><input type="tel" value={form.customer_contact} onChange={event => update('customer_contact', event.target.value)} placeholder="+7 999 000-00-00" /></label>
        <BookingSetupNotice className="full"/>
        <BookingQuestions form={form} update={update} attempted={attempted}/><label className="full"><span>Комментарий</span><textarea value={form.comment} onChange={event => update('comment', event.target.value)} placeholder="Необязательное поле: важные детали" /></label>
        <AttachmentPicker files={files} onChange={setFiles} hint="Файлы будут видны во всех бронированиях серии. До 10 файлов, каждый до 20 МБ." />
      </div>
      {searchReady && <p className={`user-search-status ${leadError?'invalid-date':'ready'}`}><Search />{leadError ? 'Неподходящая дата' : checking ? 'Ищем свободные аудитории…' : availability ? `Найдено свободных аудиторий: ${availability.free.length}. Список обновляется сам при изменении параметров.` : 'Подбираем аудитории…'}</p>}
    </section>
    <aside className="user-match-pane"><section className="user-availability">
      <header><div><small>{availability ? 'РЕЗУЛЬТАТ ПОДБОРА' : 'ПОДХОДЯЩИЕ ВАРИАНТЫ'}</small><h2>{availability ? 'Свободные аудитории' : 'Подходящие аудитории'}</h2><p>{availability ? `${seriesLongDate(form.date)}${periodReady ? ` — ${seriesLongDate(form.date_end)}` : ''}, ${form.time_start}–${form.time_end} · ${form.participants} участников` : 'Укажите дату, время и количество участников, чтобы проверить занятость.'}</p></div><span>{shown.length}</span></header>
      {selectedRooms.length>0&&<ExtraRoomsGuide request={request} count={selectedRooms.length} variant="series"/>}
      {shown.length ? <div className="user-available-grid">{shown.map(room => <button type="button" className={isSelected(room) ? 'selected' : ''} onClick={() => toggleRoom(room)} key={room.id}><img src={room.images?.[0]} alt="" /><div><small>{room.building}</small><h3>Аудитория {room.number}</h3><p>{room.capacity} мест</p>{room.pending_requests?.length > 0 && <em className="soft-request-warning">Есть ещё заявок: {room.pending_requests.length}</em>}{busyDates(room).length > 0 && <em className="soft-request-warning series-busy-warning">Занята в даты серии: {busyDates(room).slice(0, 6).map(seriesShortDate).join(', ')}{busyDates(room).length > 6 ? ` и ещё ${busyDates(room).length - 6}` : ''}</em>}</div>{isSelected(room) ? <Check /> : availability ? <ChevronRight /> : <Clock3 />}</button>)}</div>
        : <div className="user-no-availability"><AlertCircle /><b>{availability ? 'Свободных аудиторий нет' : 'Подходящих аудиторий нет'}</b><span>Измените вместимость или корпус.</span></div>}
      {error && <p className="error admin-series-error">{error}</p>}
      <footer><div><Check /><span><small>ВЫБРАНО ДЛЯ СЕРИИ</small><b>{selectedRooms.length ? selectedRooms.map(room => room.number).join(', ') : 'Аудитории не выбраны'}</b></span></div><button className="primary" disabled={saving} onClick={submit}><Copy />{saving ? 'Создаём…' : 'Создать серию'}</button></footer>
    </section></aside>
  </div></div></div>;
}


export function TransferDialog({ item, rooms, request, close, done }) { const [saving, setSaving] = useState(false); const [error, setError] = useState(''); const submit = async event => { event.preventDefault(); setSaving(true); setError(''); const data = Object.fromEntries(new FormData(event.currentTarget)); data.room_id = Number(data.room_id); data.participants = item.participants || null; data.requested_equipment = item.requested_equipment || []; data.booking_type = item.booking_type || 'other'; data.group_name = item.group_name || null; data.teacher = item.teacher || null; data.catering_required = data.catering_required === 'yes'; data.technical_support_required = data.technical_support_required === 'yes'; data.department_id = item.department_id || null; data.notify_customer = Boolean(data.notify_customer); try { await request(`/api/admin/booking-center/${item.id}/transfer`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }); done() } catch (failure) { setError(failure.message); setSaving(false) } }; return <DialogShell title="Перенести бронирование" eyebrow={`БРОНЬ № ${item.id}`} close={close}><form className="operation-form" onSubmit={submit}><div className="full transfer-origin"><Repeat2 /><span><small>ИСХОДНАЯ БРОНЬ</small><b>{dateLabel(item.date)}, {item.time_start}–{item.time_end}</b><em>{item.building} · аудитория {item.room_number}</em></span></div><label className="full"><span>Новая аудитория</span><select name="room_id" defaultValue={item.room_id} required>{rooms.map(room => <option value={room.id} key={room.id}>Ауд. {room.number} · {room.building}</option>)}</select></label><label className={error.includes('7 рабочих дней')?'lead-date-invalid':''}><span>Новая дата</span><input name="date" type="date" onChange={() => setError('')} required />{error.includes('7 рабочих дней')&&<small className="booking-lead-warning" role="alert">{error}</small>}</label><label><span>Начало</span><TimeSelect name="time_start" /></label><label><span>Окончание</span><TimeSelect name="time_end" /></label><label className="full"><span>Название</span><input name="title" defaultValue={item.title} required minLength="2" /></label><BookingSetupNotice className="full"/><label className="full"><span>Причина переноса</span><textarea name="reason" required minLength="3" placeholder="Почему и по чьей договорённости переносится бронь" /></label><label><span>Требуется аудитория для питания *</span><select name="catering_required" required defaultValue={item.catering_required===true?'yes':item.catering_required===false?'no':''}><option value="">Выберите</option><option value="yes">Да</option><option value="no">Нет</option></select></label><label><span>Материально-техническое обеспечение *</span><select name="technical_support_required" required defaultValue={item.technical_support_required===true?'yes':item.technical_support_required===false?'no':''}><option value="">Выберите</option><option value="yes">Да</option><option value="no">Нет</option></select></label><input type="hidden" name="comment" value={item.comment || ''} /><label className="full check-line"><input type="checkbox" name="notify_customer" defaultChecked /><span>Нужно дополнительно сообщить заказчику о переносе</span></label>{error && <p className="error full">{error}</p>}<footer className="full"><button type="button" className="secondary" onClick={close}>Отмена</button><button className="primary" disabled={saving}><Repeat2 />{saving ? 'Переносим…' : 'Перенести и сохранить историю'}</button></footer></form></DialogShell> }


export function DepartmentsDialog({ departments, request, close, done }) { const [error, setError] = useState(''); const submit = async event => { event.preventDefault(); const form = event.currentTarget; const data = new FormData(form); try { await request('/api/admin/departments', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: String(data.get('name') || '').trim() }) }); form.reset(); done() } catch (failure) { setError(failure.message) } }; const remove = async item => { if (!window.confirm(`Удалить подразделение «${item.name}»?`)) return; setError(''); try { const result = await request(`/api/admin/departments/${item.id}`, { method: 'DELETE' }); done(result?.archived ? 'Подразделение скрыто из справочника: оно используется в заявках' : 'Подразделение удалено') } catch (failure) { setError(failure.message) } }; return <DialogShell title="Подразделения" eyebrow="СПРАВОЧНИК ПОДРАЗДЕЛЕНИЙ" close={close}><div className="departments-dialog"><form className="operation-form" onSubmit={submit}><label className="full"><span>Название подразделения</span><input name="name" required minLength={2} maxLength={250} placeholder="Введите название подразделения" /></label>{error && <p className="error full">{error}</p>}<footer className="full"><button className="primary"><Users />Сохранить</button></footer></form><div className="department-list department-list-name-only">{departments.map(item => <article key={item.id}><span><strong>{item.name}</strong></span><button type="button" className="department-remove" title="Удалить подразделение" aria-label={`Удалить подразделение ${item.name}`} onClick={() => remove(item)}><X size={16} /></button></article>)}</div></div></DialogShell> }


function TimeSelect({ name }) { return <select name={name} defaultValue="" required><option value="" disabled>Выберите время</option>{times.map(value => <option key={value}>{value}</option>)}</select> }
function DialogShell({ title, eyebrow, close, children }) { return <div className="center-modal nested"><button className="center-backdrop" onClick={close} /><section className="operation-dialog"><header><div><small>{eyebrow}</small><h2>{title}</h2></div><button className="icon" onClick={close}><X /></button></header>{children}</section></div> }
