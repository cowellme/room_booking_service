import { Building2, Clock3 } from "lucide-react";
import "./roomSets.css";
import AdminExtraRoomsPicker from "./AdminExtraRoomsPicker";

// Typical purposes of an extra room; "Другое" lets the person type their own.
export const EXTRA_ROOM_PURPOSES = ["Штаб", "Хранение вещей", "Гардероб", "Зона питания", "Переговорная", "Зона регистрации"];
export const MAX_EXTRA_ROOMS = 10;
const OTHER = "__other";
const STATUS_LABELS = {
  pending: "На согласовании",
  approved: "Подтверждено",
  rejected: "Отклонено",
  cancelled: "Отменено",
  cancelled_by_user: "Отменено",
  cancelled_by_admin: "Отменено администратором",
  completed: "Состоялось",
  no_show: "Неявка",
  transferred: "Перенесено",
};
export const OPEN_SET_STATUSES = ["pending", "approved"];

const purposeOf = (row) => (row.purpose === OTHER ? row.purpose_other : row.purpose || "").trim();

export const extraRoomsReady = (rows) => rows.every((row) => row.room_id && purposeOf(row).length >= 2);
export const extraRoomsPayload = (rows) =>
  rows.map((row) => ({
    room_id: Number(row.room_id),
    purpose: purposeOf(row),

  }));

// Moves the extra rooms of a set into their main booking (as `set_extras`) and drops them from the list,
// so a set shows up as one card. Extra rooms whose main booking is not in the list stay as they are.
export function attachRoomSets(items) {
  const ids = new Set(items.map((item) => item.id));
  const extras = new Map();
  for (const item of items)
    if (item.parent_booking_id && ids.has(item.parent_booking_id)) {
      if (!extras.has(item.parent_booking_id)) extras.set(item.parent_booking_id, []);
      extras.get(item.parent_booking_id).push(item);
    }
  return items
    .filter((item) => !(item.parent_booking_id && ids.has(item.parent_booking_id)))
    .map((item) => (extras.has(item.id) ? { ...item, set_extras: extras.get(item.id) } : item));
}

// Form block "Дополнительные аудитории": shown after the main room is chosen.
export function ExtraRoomsPicker(props) {
  return <AdminExtraRoomsPicker {...props} purposes={EXTRA_ROOM_PURPOSES} maxRooms={MAX_EXTRA_ROOMS}/>;
}

export function RoomSetCards({ main, extras = [], actions }) {
  if (!extras.length) return null;
  return <section className="room-set-cards" aria-label="Аудитории комплекта">
    {[main,...extras].map((room,index)=><article key={room.id} className="room-set-equal-card" style={{'--set-room-color':room.color||'#007895'}}>
      <div className="room-set-equal-heading"><span>{index===0?'Основная':`Дополнительная · ${room.room_purpose||'назначение не указано'}`}</span><em className={`status ${room.status}`}>{STATUS_LABELS[room.status]||room.status}</em></div>
      <div className="room-set-equal-building"><Building2/>Корпус: {room.building}</div>
      <strong>Аудитория {room.room_number}</strong>
      <div className="room-set-equal-time">{room.has_conflict&&'Аудитория занята на эту дату'}</div>
      {index>0&&actions?.(room)}
    </article>)}
  </section>;
}

// Read-only list of the extra rooms in a card. `actions(extra)` may return buttons for one room.
export function RoomSetList({ extras = [], title = "Дополнительные аудитории", actions, collapsible = false }) {
  if (!extras.length) return null;
  const content = (
    <section className="room-set-list">
      <h4>
        <Building2 />
        {title}
        <b>{extras.length}</b>
      </h4>
      <ul>
        {extras.map((extra) => (
          <li key={extra.id} className={OPEN_SET_STATUSES.includes(extra.status) ? "" : "closed"} style={{"--set-room-color":extra.color||"#007895"}}>
            <span>
              <small className="room-set-building"><Building2 />Корпус: {extra.building}</small>
              <b>Аудитория {extra.room_number}</b>
              <small className="room-set-purpose">Назначение: {extra.room_purpose || "не указано"}</small>
              <small>
                <Clock3 />

                {extra.has_conflict ? "Аудитория занята на эту дату" : ""}
              </small>
            </span>
            <em className={`status ${extra.status}`}>{STATUS_LABELS[extra.status] || extra.status}</em>
            {actions?.(extra)}
          </li>
        ))}
      </ul>
    </section>
  );
  return collapsible ? <details className="room-set-expand" open><summary>Дополнительные аудитории <b>{extras.length}</b></summary>{content}</details> : content;
}
