import {
  bookingDatesReady,
  bookingPeriodLabel,
  changeBookingDate,
} from "./bookingDates";
import { firstSeriesDate } from "./seriesDates";
import ReviewDeadline from "./ReviewDeadline";
import BookingQuestions, {
  bookingQuestionAnswers,
  missingBookingQuestions,
} from "./BookingQuestions";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  Archive,
  Building2,
  CalendarCheck,
  Check,
  ChevronRight,
  Clock3,
  History,
  Eye,
  Folder,
  FolderInput,
  Hash,
  MapPin,
  Plus,
  Search,
  Send,
  ShieldCheck,
  Star,
  Trash2,
  Users,
  Wrench,
  X,
} from "lucide-react";
import { localIso } from "./bookingCenterConfig";
import RoomEquipmentBlock from "./RoomEquipmentBlock";
import {
  AttachmentList,
  AttachmentPicker,
  FileReplacementHistory,
  submitRequestWithFile,
} from "./BookingAttachments";
import {
  ExtraRoomsPicker,
  RoomSetList,
  RoomSetCards,
  attachRoomSets,
  extraRoomsPayload,
  extraRoomsReady,
} from "./RoomSets";
import ExtraRoomsGuide from "./ExtraRoomsGuide";
import EventFormatField, {
  eventFormatReady,
  eventFormatState,
  eventFormatValue,
} from "./EventFormatField";
import DepartmentSelect from "./DepartmentSelect";
import ObservedBookings from "./ObservedBookings";
import "./userBookingAdminMirror.css";

const STATUS = {
  pending: {
    label: "На согласовании",
    hint: "Заявка отправлена администратору",
    tone: "pending",
  },
  in_progress: {
    label: "Принята в работу",
    hint: "Администратор рассматривает заявку. Бронь пока не подтверждена",
    tone: "in-progress",
  },
  approved: {
    label: "Подтверждено",
    hint: "Аудитория забронирована",
    tone: "approved",
  },
  rejected: {
    label: "Отклонено",
    hint: "Администратор отказал в бронировании",
    tone: "rejected",
  },
  cancelled: {
    label: "Отменено",
    hint: "Бронирование отменено",
    tone: "cancelled",
  },
  cancelled_by_user: {
    label: "Отменено вами",
    hint: "Отмена сохранена в истории",
    tone: "cancelled_by_user",
  },
  cancelled_by_admin: {
    label: "Отменено администратором",
    hint: "Посмотрите причину отмены",
    tone: "cancelled_by_admin",
  },
  completed: {
    label: "Состоялось",
    hint: "Мероприятие завершено",
    tone: "completed",
  },
  no_show: { label: "Неявка", hint: "Зафиксирована неявка", tone: "no_show" },
  transferred: {
    label: "Перенесено",
    hint: "Исходная бронь сохранена в истории",
    tone: "transferred",
  },
};
const CLOSED = [
  "rejected",
  "cancelled",
  "cancelled_by_user",
  "cancelled_by_admin",
  "completed",
  "no_show",
  "transferred",
];
const today = () => localIso();
const formatDate = (value) =>
  new Date(`${value}T00:00:00`).toLocaleDateString("ru-RU", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
// A series card shows the state of its dates that still matter: one expired first date must not make the whole series look rejected.
const SERIES_STATUS_PRIORITY = [
  "pending",
  "in_progress",
  "approved",
  "completed",
  "no_show",
];
const seriesRepresentative = (group) =>
  SERIES_STATUS_PRIORITY.map((status) =>
    group.find((entry) => entry.status === status),
  ).find(Boolean) || group[0];
const nowStamp = () => {
  const now = new Date();
  return `${localIso()} ${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
};
const canCancelEntry = (entry) =>
  entry.status === "pending" ||
  (!CLOSED.includes(entry.status) &&
    `${entry.date} ${String(entry.time_start).slice(0, 5)}` > nowStamp());
const groupSeriesItems = (items) => {
  const groups = new Map();
  for (const item of items) {
    const key = item.series_id ? "series:" + item.series_id : "item:" + item.id;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  }
  return [...groups.values()].map((group) => {
    group.sort((a, b) =>
      String(a.date + " " + a.time_start).localeCompare(
        String(b.date + " " + b.time_start),
      ),
    );
    const first = group[0];
    const shown = seriesRepresentative(group);
    return group.length === 1
      ? first
      : {
          ...shown,
          series_items: group,
          series_count: group.length,
          series_dates: [group[0].date, group[group.length - 1].date],
        };
  });
};
const cleanDate = (value) => formatDate(value).replace(/\s*г\.$/, "");
const weekdayOf = (value, width) =>
  new Date(`${value}T00:00:00`).toLocaleDateString("ru-RU", { weekday: width });
const monthShort = (value) =>
  new Date(`${value}T00:00:00`)
    .toLocaleDateString("ru-RU", { month: "short" })
    .replace(".", "");
const dateRange = (from, to) => {
  if (from === to) return cleanDate(from);
  const a = new Date(`${from}T00:00:00`),
    b = new Date(`${to}T00:00:00`);
  if (a.getFullYear() !== b.getFullYear())
    return `${cleanDate(from)} — ${cleanDate(to)}`;
  const head =
    a.getMonth() === b.getMonth()
      ? String(a.getDate())
      : a.toLocaleDateString("ru-RU", { day: "numeric", month: "long" });
  return `${head} — ${cleanDate(to)}`;
};
const durationLabel = (start, end) => {
  const [h1, m1] = start.split(":").map(Number),
    [h2, m2] = end.split(":").map(Number);
  const total = h2 * 60 + m2 - h1 * 60 - m1,
    hours = Math.floor(total / 60),
    minutes = total % 60;
  return [hours ? `${hours} ч` : "", minutes ? `${minutes} мин` : ""]
    .filter(Boolean)
    .join(" ");
};
const plural = (count, one, few, many) => {
  const n = Math.abs(count) % 100,
    last = n % 10;
  return n > 10 && n < 20
    ? many
    : last === 1
      ? one
      : last >= 2 && last <= 4
        ? few
        : many;
};
const chronological = (a, b) =>
  `${a.date || ""} ${a.time_start || ""} ${a.time_end || ""}`.localeCompare(
    `${b.date || ""} ${b.time_start || ""} ${b.time_end || ""}`,
  ) || Number(a.id || 0) - Number(b.id || 0);

export default function UserBookingPortal({
  request,
  notice,
  user,
  rooms,
  buildings,
  onChanged,
  goToRooms,
  focusedBooking,
  initialRoom,
  clearInitialRoom,
  active = true,
  refreshKey = 0,
  seriesRequest,
  clearSeriesRequest,
}) {
  const [items, setItems] = useState([]);
  // The user's landing view is their submitted bookings; creating a new
  // request remains available as a separate tab.
  const [tab, setTab] = useState("history");
  const [loading, setLoading] = useState(true);
  const [availability, setAvailability] = useState(null);
  const [selected, setSelected] = useState(null);
  const [checking, setChecking] = useState(false);
  const [saving, setSaving] = useState(false);
  const [cancelTarget, setCancelTarget] = useState(null);
  const resultsRef = useRef(null);
  const checkSeq = useRef(0);
  const [seriesMode, setSeriesMode] = useState(false);
  const [seriesRooms, setSeriesRooms] = useState([]);
  const [seriesWeekdays, setSeriesWeekdays] = useState([0, 1, 2, 3, 4]);
  const [guideOpen, setGuideOpen] = useState(() => {
    try {
      return localStorage.getItem("room-booking-user-guide-seen") !== "1";
    } catch {
      return true;
    }
  });
  const [attempted, setAttempted] = useState(false);
  const closeGuide = () => {
    setGuideOpen(false);
    try {
      localStorage.setItem("room-booking-user-guide-seen", "1");
    } catch {}
  };
  const emptyForm = {
    date: "",
    date_end: "",
    participants: "",
    building_id: "",
    title: "",
    ...eventFormatState(),
    comment: "",
    department_id: "",
    department_name: user?.department || "",
    customer_name: user?.full_name || "",
    external_reference: "",
    customer_contact: user?.phone || "",
  };
  const [form, setForm] = useState(emptyForm);
  const [departments, setDepartments] = useState([]);
  const [seriesBusy, setSeriesBusy] = useState({});
  const [files, setFiles] = useState([]);
  const [extraRooms, setExtraRooms] = useState([]);
  useEffect(() => {
    request("/api/departments")
      .then((list) => {
        setDepartments(list);
        setForm((current) => {
          if (current.department_id) return current;
          const known = list.find(
            (item) =>
              item.name.toLowerCase() ===
              String(current.department_name || "")
                .trim()
                .toLowerCase(),
          );
          return known
            ? { ...current, department_id: String(known.id) }
            : { ...current, department_id: "" };
        });
      })
      .catch(() => {});
  }, []);
  const load = () => {
    setLoading(true);
    return request("/api/me/bookings")
      .then((data) =>
        setItems(
          [...data].sort(
            (a, b) =>
              String(b.created_at || b.date + " " + b.time_start).localeCompare(
                String(a.created_at || a.date + " " + a.time_start),
              ) || chronological(b, a),
          ),
        ),
      )
      .catch((error) => notice(error.message))
      .finally(() => setLoading(false));
  };
  useEffect(() => {
    if (active) load();
  }, [active, refreshKey]);
  useEffect(() => {
    if (!initialRoom) return;
    setTab("request");
    setForm((current) => ({
      ...current,
      building_id: String(initialRoom.building_id),
    }));
    setSelected(initialRoom);
    setAvailability(null);
  }, [initialRoom]);
  useEffect(() => {
    if (focusedBooking?.id) setTab("history");
  }, [focusedBooking?.token]);
  useEffect(() => {
    if (!seriesRequest) return;
    setTab("request");
    setSeriesMode(true);
    setSeriesRooms(seriesRequest.room ? [seriesRequest.room] : []);
    setAvailability(null);
    clearSeriesRequest?.();
  }, [seriesRequest?.token]);
  const equipmentRooms = (seriesMode ? seriesRooms : [selected || initialRoom])
    .filter(Boolean)
    .map((room) => rooms.find((item) => item.id === room.id) || room);
  const candidateRooms = useMemo(
    () =>
      rooms
        .filter(
          (room) =>
            (!form.building_id ||
              String(room.building_id) === String(form.building_id)) &&
            (!Number(form.participants) ||
              Math.max(room.capacity, room.max_capacity || 0) >=
                Number(form.participants)),
        )
        .slice(0, 12),
    [rooms, form.building_id, form.participants],
  );
  // Only the search parameters invalidate the found rooms; contact fields and the comment keep the selection.
  const SEARCH_FIELDS = ["date", "date_end", "participants", "building_id"];
  const update = (key, value) => {
    setForm((current) => changeBookingDate(current, key, value));
    if (SEARCH_FIELDS.includes(key)) {
      setAvailability(null);
      setSelected(initialRoom || null);
      if (key === "date" || key === "date_end") setExtraRooms([]);
    }
  };
  const searchReady = Boolean(
    bookingDatesReady(form) && Number(form.participants) > 0,
  );
  const departmentReady = Boolean(form.department_id);
  const departmentPayload = {
    department_id: Number(form.department_id),
    department_name: null,
  };
  const requiredReady = Boolean(
    !missingBookingQuestions(form).length &&
      searchReady &&
      eventFormatReady(form) &&
      form.title.trim().length >= 2 &&
      form.customer_name.trim().length >= 2 &&
      form.customer_contact.trim().length >= 3 &&
      form.external_reference.trim().length > 0 &&
      departmentReady &&
      files.length,
  );
  const firstOccurrence = seriesMode
    ? firstSeriesDate(form.date, form.date_end, seriesWeekdays)
    : form.date;
  const check = async (silent = false) => {
    const seq = ++checkSeq.current;
    if (!searchReady || !firstOccurrence) {
      if (!silent) {
        setAttempted(true);
        notice("Укажите даты и количество участников");
      }
      return;
    }
    setChecking(true);
    try {
      const result = await request("/api/availability", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          date: firstOccurrence,
          date_end: seriesMode ? firstOccurrence : form.date_end,
          participants: Number(form.participants),
          building_id: form.building_id ? Number(form.building_id) : null,
        }),
      });
      if (seq !== checkSeq.current) return;
      setAvailability(result);
      const preferred = result.free.find((room) => room.id === initialRoom?.id);
      setSelected(preferred || null);
      window.setTimeout(
        () =>
          resultsRef.current?.scrollIntoView({
            behavior: "smooth",
            block: "nearest",
          }),
        100,
      );
    } catch (error) {
      if (seq === checkSeq.current) {
        notice(error.message);
      }
    } finally {
      if (seq === checkSeq.current) setChecking(false);
    }
  };
  useEffect(() => {
    /* A result for the previous parameters must not stay on screen or stay selected. */ checkSeq.current += 1;
    setAvailability(null);
    if (!seriesMode)
      setSelected((current) =>
        current && initialRoom && current.id === initialRoom.id
          ? current
          : null,
      );
    if (!searchReady) return;
    const timer = setTimeout(() => check(true), 450);
    return () => clearTimeout(timer);
  }, [
    firstOccurrence,
    seriesMode,
    form.date,
    form.date_end,
    form.participants,
    form.building_id,
  ]);
  useEffect(() => {
    if (
      !seriesMode ||
      !searchReady ||
      !form.date_end ||
      form.date_end < form.date ||
      !seriesWeekdays.length
    ) {
      setSeriesBusy({});
      return;
    }
    let active = true;
    const timer = setTimeout(
      () =>
        request("/api/booking-series/availability", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            date: form.date,
            date_end: form.date_end,
            weekdays: seriesWeekdays,
          }),
        })
          .then((data) => active && setSeriesBusy(data.busy || {}))
          .catch(() => active && setSeriesBusy({})),
      300,
    );
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [seriesMode, form.date, form.date_end, seriesWeekdays.join("|")]);
  const submit = async () => {
    setAttempted(true);
    if (!selected || !requiredReady) {
      notice(
        "Заполните ФИО ответственного, подразделение, номер заявки и остальные обязательные поля",
      );
      return;
    }
    if (!extraRoomsReady(extraRooms)) {
      notice(
        "Для каждой дополнительной аудитории выберите аудиторию и назначение",
      );
      return;
    }
    if (!files.length) {
      notice("Прикрепите файл с обоснованием заявки");
      return;
    }
    setSaving(true);
    try {
      await submitRequestWithFile(
        request,
        {
          room_id: selected.id,
          date: form.date,
          date_end: form.date_end,
          participants: Number(form.participants),
          event_format: eventFormatValue(form),
          title: form.title.trim(),
          booking_type: "other",
          teacher: null,
          group_name: null,
          comment: form.comment.trim() || null,
          ...bookingQuestionAnswers(form),
          ...departmentPayload,
          customer_name: form.customer_name.trim(),
          customer_contact: form.customer_contact.trim() || null,
          external_reference: form.external_reference.trim(),
          extra_rooms: extraRoomsPayload(extraRooms),
        },
        files[0],
      );
      setFiles([]);
      setExtraRooms([]);
      notice("Заявка отправлена администратору на согласование");
      setForm({
        ...emptyForm,
        department_id: form.department_id,
        department_name: form.department_name.trim(),
        customer_contact: form.customer_contact.trim(),
      });
      setAvailability(null);
      setSelected(null);
      setAttempted(false);
      clearInitialRoom?.();
      setTab("history");
      await load();
      onChanged?.();
    } catch (error) {
      notice(error.message);
    } finally {
      setSaving(false);
    }
  };
  const seriesBusyDates = (room) => seriesBusy[String(room.id)] || [];
  const toggleSeriesRoom = (room) =>
    setSeriesRooms((current) =>
      current.some((item) => item.id === room.id)
        ? current.filter((item) => item.id !== room.id)
        : [...current, room],
    );
  const toggleSeriesDay = (day) =>
    setSeriesWeekdays((current) =>
      current.includes(day)
        ? current.filter((item) => item !== day)
        : [...current, day],
    );
  const submitSeries = async () => {
    setAttempted(true);
    if (
      !requiredReady ||
      !form.date_end ||
      form.date_end < form.date ||
      !seriesWeekdays.length ||
      seriesRooms.length === 0
    ) {
      notice("Заполните поля серии и выберите хотя бы одну аудиторию");
      return;
    }
    const blocked = seriesRooms.find((room) => seriesBusyDates(room).length);
    if (blocked) {
      notice(
        `Аудитория ${blocked.number} занята в часть дат серии — выберите другую аудиторию или измените период`,
      );
      return;
    }
    if (!files.length) {
      notice("Прикрепите файл с обоснованием заявки");
      return;
    }
    setSaving(true);
    try {
      await submitRequestWithFile(
        request,
        {
          room_ids: seriesRooms.map((room) => room.id),
          date: form.date,
          date_end: form.date_end,
          weekdays: seriesWeekdays,
          event_format: eventFormatValue(form),
          title: form.title.trim(),
          booking_type: "other",
          teacher: null,
          group_name: null,
          comment: form.comment.trim() || null,
          ...bookingQuestionAnswers(form),
          participants: Number(form.participants),
          customer_name: form.customer_name.trim(),
          customer_contact: form.customer_contact.trim() || null,
          external_reference: form.external_reference.trim(),
          ...departmentPayload,
        },
        files[0],
        true,
      );
      setFiles([]);
      notice("Серия заявок отправлена администратору на согласование");
      setForm({
        ...emptyForm,
        department_id: form.department_id,
        department_name: form.department_name.trim(),
        customer_contact: form.customer_contact.trim(),
      });
      setSeriesRooms([]);
      setAvailability(null);
      setSelected(null);
      setSeriesMode(false);
      setAttempted(false);
      clearInitialRoom?.();
      setTab("history");
      await load();
      onChanged?.();
    } catch (error) {
      notice(error.message);
    } finally {
      setSaving(false);
    }
  };
  const cancelDone = async () => {
    const series = Boolean(cancelTarget?.series_items);
    setCancelTarget(null);
    notice(
      series
        ? "Серия отменена, информация сохранена в истории"
        : "Заявка отменена, информация сохранена в истории",
    );
    await load();
    onChanged?.();
  };
  return (
    <section className="content-page user-booking-portal">
      <header className="user-booking-hero">
        <div>
          <small>ЛИЧНЫЙ КАБИНЕТ</small>
          <h1>Мои бронирования</h1>
          <p>
            Подберите свободную аудиторию, отправьте заявку и следите за
            решением администратора.
          </p>
        </div>
        <button className="secondary" onClick={goToRooms}>
          <Building2 />
          Посмотреть все аудитории
        </button>
      </header>
      <div className="user-portal-tabs">
        <button
          className={tab === "history" ? "active" : ""}
          onClick={() => setTab("history")}
        >
          <History />
          Мои заявки <b>{items.length}</b>
        </button>
        <button
          className={tab === "observed" ? "active" : ""}
          onClick={() => setTab("observed")}
        >
          <Eye />
          Наблюдаемые заявки
        </button>
        <button
          className={tab === "request" && !seriesMode ? "active" : ""}
          onClick={() => {
            setTab("request");
            if (seriesMode) {
              setSeriesMode(false);
              setSeriesRooms([]);
              setAvailability(null);
              setSelected(initialRoom || null);
            }
          }}
        >
          <Send />
          Новая заявка
        </button>
        {tab === "request" && (
          <button
            className="user-guide-open"
            onClick={() => setGuideOpen(true)}
          >
            <ShieldCheck />
            Как это работает
          </button>
        )}
      </div>
      {tab === "observed" ? (
        <ObservedBookings request={request} />
      ) : tab === "request" ? (
        <div
          className={`user-request-layout ${form.building_id || availability ? "has-matches" : ""} ${seriesMode ? "series-modal-mode" : ""}`}
        >
          {seriesMode && (
            <button
              type="button"
              className="series-dismiss-backdrop"
              aria-label="Закрыть форму серии"
              onClick={() => {
                if (!saving) {
                  setSeriesMode(false);
                  setSeriesRooms([]);
                }
              }}
            />
          )}
          {seriesMode && (
            <div className="series-modal-banner">
              <div>
                <small>НОВЫЙ ФОРМАТ БРОНИРОВАНИЯ</small>
                <h2>Серия бронирований</h2>
                <p>Одна заявка на несколько дат и аудиторий</p>
              </div>
              <button
                type="button"
                className="icon"
                onClick={() => {
                  setSeriesMode(false);
                  setSeriesRooms([]);
                }}
              >
                Закрыть
              </button>
            </div>
          )}
          <section className="user-request-form">
            <header>
              <span>1</span>
              <div>
                <h2>Параметры мероприятия</h2>
                <p>
                  Сначала укажите условия — сервис покажет только подходящие
                  варианты.
                </p>
              </div>
            </header>
            {initialRoom && (
              <div
                className="user-preselected-room"
                style={{ "--room-color": initialRoom.color }}
              >
                <img src={initialRoom.images?.[0]} alt="" />
                <span>
                  <small>ВЫБРАННАЯ АУДИТОРИЯ</small>
                  <b>
                    {initialRoom.building} · аудитория {initialRoom.number}
                  </b>
                  <em>
                    {initialRoom.name} · {initialRoom.capacity} мест
                  </em>
                </span>
                <Check />
              </div>
            )}
            <div className="user-request-fields">
              <label
                className={form.date ? "complete" : attempted ? "invalid" : ""}
              >
                <span>Дата начала *</span>
                <input
                  type="date"
                  lang="ru-RU"
                  value={form.date}
                  onChange={(event) => update("date", event.target.value)}
                />
              </label>
              <label
                className={
                  bookingDatesReady(form)
                    ? "complete"
                    : attempted
                      ? "invalid"
                      : ""
                }
              >
                <span>Дата окончания *</span>
                <input
                  type="date"
                  lang="ru-RU"
                  min={form.date || undefined}
                  value={form.date_end}
                  onChange={(event) => update("date_end", event.target.value)}
                />
              </label>
              {seriesMode && (
                <div
                  className={`series-fields full ${attempted && !seriesWeekdays.length ? "invalid" : ""}`}
                >
                  <div>
                    <span>Дни повторения *</span>
                    <div className="series-weekdays">
                      {[
                        ["Пн", 0],
                        ["Вт", 1],
                        ["Ср", 2],
                        ["Чт", 3],
                        ["Пт", 4],
                        ["Сб", 5],
                        ["Вс", 6],
                      ].map(([name, day]) => (
                        <button
                          type="button"
                          className={
                            seriesWeekdays.includes(day) ? "active" : ""
                          }
                          onClick={() => toggleSeriesDay(day)}
                          key={day}
                        >
                          {name}
                        </button>
                      ))}
                    </div>
                  </div>
                  <p className="series-hint">
                    Выберите аудитории справа — заявка будет отправлена одной
                    серией на согласование.
                  </p>
                </div>
              )}
              <label
                className={
                  Number(form.participants) > 0
                    ? "complete"
                    : attempted
                      ? "invalid"
                      : ""
                }
              >
                <span>Количество участников *</span>
                <input
                  type="number"
                  min="1"
                  max="5000"
                  value={form.participants}
                  onChange={(event) =>
                    update("participants", event.target.value)
                  }
                  placeholder="Например, 25"
                />
              </label>
              <label>
                <span>Корпус</span>
                <select
                  value={form.building_id}
                  onChange={(event) =>
                    update("building_id", event.target.value)
                  }
                >
                  <option value="">Любой корпус</option>
                  {buildings.map((item) => (
                    <option value={item.id} key={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>

              <EventFormatField
                form={form}
                update={update}
                attempted={attempted}
              />
              <label
                className={`full ${form.title.trim().length >= 2 ? "complete" : attempted ? "invalid" : ""}`}
              >
                <span>Название мероприятия *</span>
                <input
                  value={form.title}
                  onChange={(event) => update("title", event.target.value)}
                  placeholder="Дополнительная профессиональная программа повышения квалификации «Регулярный менеджмент»"
                />
              </label>
              <label
                className={`full ${departmentReady ? "complete" : attempted ? "invalid" : ""}`}
              >
                <span>Подразделение *</span>
                <DepartmentSelect
                  items={departments}
                  value={form.department_id}
                  onChange={(id, chosen) =>
                    setForm((current) => ({
                      ...current,
                      department_id: id,
                      department_name: chosen.name,
                    }))
                  }
                />
              </label>
              <label
                className={
                  form.customer_name.trim().length >= 2
                    ? "complete"
                    : attempted
                      ? "invalid"
                      : ""
                }
              >
                <span>ФИО ответственного *</span>
                <input
                  value={form.customer_name}
                  onChange={(event) =>
                    update("customer_name", event.target.value)
                  }
                  placeholder="Иванова Анна Сергеевна"
                />
              </label>
              <label
                className={
                  form.external_reference.trim()
                    ? "complete"
                    : attempted
                      ? "invalid"
                      : ""
                }
              >
                <span>Номер заявки *</span>
                <input
                  value={form.external_reference}
                  onChange={(event) =>
                    update("external_reference", event.target.value)
                  }
                  maxLength={120}
                  placeholder="Введите номер заявки"
                />
              </label>
              <label
                className={
                  form.customer_contact.trim().length >= 3
                    ? "complete"
                    : attempted
                      ? "invalid"
                      : ""
                }
              >
                <span>Телефон *</span>
                <input
                  type="tel"
                  value={form.customer_contact}
                  onChange={(event) =>
                    update("customer_contact", event.target.value)
                  }
                  placeholder="+7 999 000-00-00"
                />
              </label>
              <RoomEquipmentBlock className="full" rooms={equipmentRooms} />
              <BookingQuestions
                form={form}
                update={update}
                attempted={attempted}
              />
              <div
                className={`full required-attachment ${attempted && !files.length ? "invalid" : ""}`}
              >
                <AttachmentPicker single files={files} onChange={setFiles} />
                {attempted && !files.length && (
                  <small>Прикрепите файл перед отправкой формы</small>
                )}
              </div>
              <label className="full">
                <span>Комментарий администратору</span>
                <textarea
                  value={form.comment}
                  onChange={(event) => update("comment", event.target.value)}
                  placeholder="Необязательное поле: важные детали или пожелания"
                />
              </label>
            </div>
            <button
              type="button"
              className="secondary booking-validate-fields"
              onClick={() => {
                setAttempted(true);
                if (
                  !requiredReady ||
                  (seriesMode &&
                    (!form.date_end ||
                      form.date_end < form.date ||
                      !seriesWeekdays.length))
                ) {
                  notice("Заполните выделенные обязательные поля");
                  return;
                }
                check(true);
              }}
            >
              Проверить заполнение
            </button>
            {searchReady && (
              <p className={`user-search-status ready`}>
                <Search />
                {checking
                  ? "Ищем свободные аудитории…"
                  : availability
                    ? `Найдено свободных аудиторий: ${availability.free.length}. Список обновляется сам при изменении параметров.`
                    : "Подбираем аудитории…"}
              </p>
            )}
          </section>
          {(form.building_id || availability) && (
            <RoomMatchesPanel
              request={request}
              attempted={attempted}
              extraRooms={extraRooms}
              setExtraRooms={setExtraRooms}
              seriesBusyDates={seriesBusyDates}
              seriesMode={seriesMode}
              seriesRooms={seriesRooms}
              toggleSeriesRoom={toggleSeriesRoom}
              seriesSubmit={submitSeries}
              panelRef={resultsRef}
              rooms={
                availability
                  ? availability.free.find(
                      (room) => room.id === initialRoom?.id,
                    )
                    ? availability.free.filter(
                        (room) => room.id === initialRoom.id,
                      )
                    : availability.free
                  : initialRoom
                    ? [initialRoom]
                    : candidateRooms
              }
              availability={availability}
              form={form}
              selected={selected}
              select={(room) => {
                if (room)
                  setExtraRooms((current) =>
                    current.filter(
                      (extra) => Number(extra.room_id) !== Number(room.id),
                    ),
                  );
                else if (initialRoom) clearInitialRoom?.();
                setSelected(room);
              }}
              saving={saving}
              submit={submit}
            />
          )}
        </div>
      ) : (
        <UserBookingHistory
          items={items}
          loading={loading}
          focusedBooking={focusedBooking}
          cancel={setCancelTarget}
          request={request}
          user={user}
          reload={load}
        />
      )}
      {guideOpen && tab === "request" && (
        <div className="user-guide-overlay" role="dialog" aria-modal="true">
          <button
            className="user-guide-backdrop"
            aria-label="Закрыть"
            onClick={closeGuide}
          />
          <aside className="user-request-guide user-guide-popup">
            <button
              className="user-guide-close"
              aria-label="Закрыть"
              onClick={closeGuide}
            >
              <X />
            </button>
            <h3>Как это работает</h3>
            {[
              ["1", "Заполните параметры"],
              ["2", "Выберите свободную аудиторию"],
              ["3", "Отправьте заявку"],
              ["4", "Получите решение администратора"],
            ].map(([number, text]) => (
              <div key={number}>
                <b>{number}</b>
                <span>{text}</span>
              </div>
            ))}
            <p>
              <ShieldCheck />
              До подтверждения заявка не считается окончательной бронью.
            </p>
          </aside>
        </div>
      )}
      {cancelTarget && (
        <UserCancelDialog
          item={cancelTarget}
          request={request}
          close={() => setCancelTarget(null)}
          done={cancelDone}
        />
      )}
    </section>
  );
}

function RoomMatchesPanel({
  request,
  attempted,
  extraRooms,
  setExtraRooms,
  panelRef,
  rooms,
  availability,
  form,
  selected,
  select,
  saving,
  submit,
  seriesMode,
  seriesRooms,
  toggleSeriesRoom,
  seriesSubmit,
  seriesBusyDates,
}) {
  const shortDate = (value) =>
    new Date(`${value}T00:00:00`).toLocaleDateString("ru-RU", {
      day: "2-digit",
      month: "2-digit",
    });
  return (
    <aside className="user-match-pane" ref={panelRef}>
      <section className="user-availability">
        <header>
          <div>
            <small>
              {availability ? "РЕЗУЛЬТАТ ПОДБОРА" : "ПОДХОДЯЩИЕ ВАРИАНТЫ"}
            </small>
            <h2>
              {availability ? "Свободные аудитории" : "Подходящие аудитории"}
            </h2>
            <p>
              {availability
                ? `${bookingPeriodLabel(form.date, form.date_end)} · ${form.participants} участников`
                : "Укажите даты и количество участников, чтобы проверить занятость."}
            </p>
          </div>
          <span>{rooms.length}</span>
        </header>
        {seriesMode && seriesRooms?.length > 0 && (
          <ExtraRoomsGuide
            request={request}
            count={seriesRooms.length}
            variant="series"
          />
        )}
        {rooms.length ? (
          <div className="user-available-grid">
            {(!seriesMode && selected && availability
              ? rooms.filter((room) => room.id === selected.id)
              : rooms
            ).map((room) => (
              <button
                type="button"
                className={
                  seriesMode
                    ? seriesRooms?.some((item) => item.id === room.id)
                      ? "selected"
                      : ""
                    : selected?.id === room.id
                      ? "selected"
                      : ""
                }
                onClick={() =>
                  availability &&
                  (seriesMode
                    ? seriesBusyDates(room).length &&
                      !seriesRooms?.some((item) => item.id === room.id)
                      ? null
                      : toggleSeriesRoom(room)
                    : select(room))
                }
                key={room.id}
              >
                <img src={room.images?.[0]} alt="" />
                <div>
                  <small>{room.building}</small>
                  <h3>Аудитория {room.number}</h3>
                  <p>
                    {room.capacity} мест
                    {room.over_capacity ? " (нужны доп. места)" : ""}
                  </p>
                  {room.pending_requests?.length > 0 && (
                    <em className="soft-request-warning">
                      Есть ещё заявок: {room.pending_requests.length}
                    </em>
                  )}
                  {seriesMode && seriesBusyDates(room).length > 0 && (
                    <em className="soft-request-warning series-busy-warning">
                      Занята в даты серии:{" "}
                      {seriesBusyDates(room)
                        .slice(0, 6)
                        .map(shortDate)
                        .join(", ")}
                      {seriesBusyDates(room).length > 6
                        ? ` и ещё ${seriesBusyDates(room).length - 6}`
                        : ""}
                    </em>
                  )}
                </div>
                {seriesMode ? (
                  seriesRooms?.some((item) => item.id === room.id) ? (
                    <Check />
                  ) : (
                    <ChevronRight />
                  )
                ) : availability ? (
                  selected?.id === room.id ? (
                    <Check />
                  ) : (
                    <ChevronRight />
                  )
                ) : (
                  <Clock3 />
                )}
              </button>
            ))}
          </div>
        ) : (
          <div className="user-no-availability">
            <AlertCircle />
            <b>
              {availability
                ? "Свободных аудиторий нет"
                : "Подходящих аудиторий нет"}
            </b>
            <span>Измените вместимость, корпус или оснащение.</span>
          </div>
        )}
        {seriesMode && seriesRooms?.length > 0 && (
          <footer>
            <div>
              <Check />
              <span>
                <small>ВЫБРАНО ДЛЯ СЕРИИ</small>
                <b>{seriesRooms.length} аудиторий</b>
              </span>
            </div>
            <button
              className="primary"
              disabled={saving}
              onClick={seriesSubmit}
            >
              <Send />
              {saving ? "Отправляем…" : "Отправить серию на согласование"}
            </button>
          </footer>
        )}
        {availability && selected && !seriesMode && (
          <button
            type="button"
            className="secondary change-selected-room"
            onClick={() => select(null)}
          >
            Выбрать другую аудиторию
          </button>
        )}
        {availability && selected && !seriesMode && (
          <ExtraRoomsPicker
            request={request}
            availabilityUrl="/api/availability"
            date={form.date}
            dateEnd={form.date_end}
            mainRoomId={selected.id}
            value={extraRooms}
            onChange={setExtraRooms}
            attempted={attempted}
          />
        )}
        {availability && selected && !seriesMode && (
          <footer>
            <div>
              <Check />
              <span>
                <small>ВЫБРАНО</small>
                <b>
                  {selected.building} · аудитория {selected.number}
                </b>
              </span>
            </div>
            <button className="primary" disabled={saving} onClick={submit}>
              <Send />
              {saving ? "Отправляем…" : "Отправить на согласование"}
            </button>
          </footer>
        )}
      </section>
    </aside>
  );
}

const HISTORY_STATUS_FILTERS = [
  ["archive", "Архив", null],
  ["all", "Все", null],
  ["active", "Активные", ["pending", "in_progress", "approved"]],
  ["pending", "На согласовании", ["pending"]],
  ["in_progress", "В работе", ["in_progress"]],
  ["approved", "Подтверждённые", ["approved"]],
  ["completed", "Состоявшиеся", ["completed"]],
  ["rejected", "Отклонённые", ["rejected"]],
  [
    "cancelled",
    "Отменённые",
    ["cancelled", "cancelled_by_user", "cancelled_by_admin"],
  ],
];
const HISTORY_KIND_FILTERS = [
  ["all", "Все заявки"],
  ["single", "Обычные"],
  ["series", "Серии"],
];

function UserBookingHistory({
  items,
  loading,
  focusedBooking,
  cancel,
  request,
  user,
  reload,
}) {
  const [filter, setFilter] = useState("all");
  const [kind, setKind] = useState("all");
  const [searchFilters, setSearchFilters] = useState({ title: "", number: "", room: "", building: "", type: "", period: "" });
  const [highlighted, setHighlighted] = useState(null);
  const [customFolders, setCustomFolders] = useState(() => { try { return JSON.parse(localStorage.getItem(`user-booking-folders-${user?.id}`) || "[]"); } catch { return []; } });
  const [folderAssignments, setFolderAssignments] = useState(() => { try { return JSON.parse(localStorage.getItem(`user-booking-folder-assignments-${user?.id}`) || "{}"); } catch { return {}; } });
  const [tags, setTags] = useState(() => { try { return JSON.parse(localStorage.getItem(`user-booking-tags-${user?.id}`) || "{}"); } catch { return {}; } });
  const [draggedBooking, setDraggedBooking] = useState(null);
  const [detail, setDetail] = useState(null);
  const [contextMenu, setContextMenu] = useState(null);
  const [contextPanel, setContextPanel] = useState(null);
  const [tagDraft, setTagDraft] = useState("");
  const [favorites, setFavorites] = useState(() => { try { return JSON.parse(localStorage.getItem(`user-booking-favorites-${user?.id}`) || "{}"); } catch { return {}; } });
  const saveUserState = (folders, assignments, nextTags) => { try { localStorage.setItem(`user-booking-folders-${user?.id}`, JSON.stringify(folders)); localStorage.setItem(`user-booking-folder-assignments-${user?.id}`, JSON.stringify(assignments)); localStorage.setItem(`user-booking-tags-${user?.id}`, JSON.stringify(nextTags)); } catch {} };
  const addUserFolder = () => { const name = window.prompt("Название папки"); const clean = name?.trim(); if (!clean) return; const next = [...customFolders, { id: `user-folder-${Date.now()}`, name: clean }]; setCustomFolders(next); saveUserState(next, folderAssignments, tags); };
  const assignToFolder = folderId => { if (!draggedBooking) return; const next = {...folderAssignments, [draggedBooking]: folderId}; setFolderAssignments(next); saveUserState(customFolders, next, tags); setDraggedBooking(null); };
  const addTag = bookingId => { const name = window.prompt("Название тега"); const clean = name?.trim(); if (!clean) return; const next = {...tags, [bookingId]: [...new Set([...(tags[bookingId] || []), clean])].slice(0, 6)}; setTags(next); saveUserState(customFolders, folderAssignments, next); };
  const addTagValue = (bookingId, value) => { const clean = value.trim(); if (!clean) return; const next = {...tags, [bookingId]: [...new Set([...(tags[bookingId] || []), clean])].slice(0, 12)}; setTags(next); saveUserState(customFolders, folderAssignments, next); setTagDraft(""); };
  const toggleFavorite = bookingId => { const next = {...favorites, [bookingId]: !favorites[bookingId]}; setFavorites(next); localStorage.setItem(`user-booking-favorites-${user?.id}`, JSON.stringify(next)); };
  const openContextMenu = (event, item) => { event.preventDefault(); event.stopPropagation(); setContextPanel(null); setTagDraft(""); setContextMenu({item, x: Math.min(event.clientX, window.innerWidth - 315), y: Math.min(event.clientY, window.innerHeight - 360)}); };
  useEffect(() => { if (!contextMenu) return; const close = event => { if (!event.target.closest?.(".user-request-context,.user-request-submenu")) { setContextMenu(null); setContextPanel(null); } }; const escape = event => { if (event.key === "Escape") { setContextMenu(null); setContextPanel(null); } }; document.addEventListener("pointerdown", close); document.addEventListener("keydown", escape); return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", escape); }; }, [contextMenu]);
  useEffect(() => {
    if (!focusedBooking?.id) return;
    setFilter("all");
    setKind("all");
    setHighlighted(focusedBooking.id);
    const scroll = setTimeout(
      () =>
        document
          .querySelector(`[data-booking-ids~="${focusedBooking.id}"]`)
          ?.scrollIntoView({ behavior: "smooth", block: "center" }),
      140,
    );
    const clear = setTimeout(() => setHighlighted(null), 4200);
    return () => {
      clearTimeout(scroll);
      clearTimeout(clear);
    };
  }, [focusedBooking?.token, loading, items.length]);
  const statuses = filter === "archive" ? null : (filter === "all" ? ["pending", "in_progress", "approved"] : HISTORY_STATUS_FILTERS.find(([value]) => value === filter)?.[2]);
  const filtered = groupSeriesItems(
    attachRoomSets(items).filter(
      (item) =>
        (filter === "archive" ? (Boolean(item.archived_at) || folderAssignments[item.id] === "__archive") : (!item.archived_at && folderAssignments[item.id] !== "__archive")) && ["pending", "in_progress", "approved"].includes(item.status) &&
        (!statuses ||
          [item, ...(item.set_extras || [])].some((entry) =>
            statuses.includes(entry.status),
          )) &&
        (kind === "all" || (kind === "series") === Boolean(item.series_id)) &&
        (!searchFilters.title || String(item.title || "").toLocaleLowerCase().includes(searchFilters.title.toLocaleLowerCase())) &&
        (!searchFilters.number || String(item.external_reference || "").toLocaleLowerCase().includes(searchFilters.number.toLocaleLowerCase())) &&
        (!searchFilters.room || String(item.room_number || "").includes(searchFilters.room)) &&
        (!searchFilters.building || String(item.building || "") === searchFilters.building) &&
        (!searchFilters.type || String(item.event_format || item.booking_type || "") === searchFilters.type) &&
        (!searchFilters.period || String(item.date || "").startsWith(searchFilters.period)) &&
        (!customFolders.some(folder => folder.id === filter) || folderAssignments[item.id] === filter),
    ),
  );
  return (
    <section className="user-booking-history">
      <header className="booking-center-heading user-booking-register-heading">
        <div><small>ЛИЧНЫЙ КАБИНЕТ</small><h2>Мои бронирования</h2></div>
      </header>
      <div className="booking-center-controls user-booking-controls">
        <div className="booking-tabs">
          {[["all", "Все бронирования"], ["active", "В работе"], ["approved", "Подтверждённые"], ["archive", "Архив"]].map(([value, label]) => (
            <button type="button" className={filter === value ? "active" : ""} onClick={() => setFilter(value)} key={value}>{label}</button>
          ))}
        </div>
        <div className="booking-scope"><button type="button" className="active">Только мои</button></div>
      </div>
      <section className="admin-booking-filters user-booking-filters" aria-label="Фильтры бронирований">
        <header><div><Search /></div><small>{filtered.length} {plural(filtered.length, "запись", "записи", "записей")}</small></header>
        <div className="admin-booking-filter-grid">
        <label><span>Название программы</span><input value={searchFilters.title} onChange={event => setSearchFilters({...searchFilters, title: event.target.value})} placeholder="Введите название" /></label>
        <label><span>Номер заявки</span><input value={searchFilters.number} onChange={event => setSearchFilters({...searchFilters, number: event.target.value})} placeholder="Введите номер" /></label>
        <label><span>Аудитория</span><input value={searchFilters.room} onChange={event => setSearchFilters({...searchFilters, room: event.target.value})} placeholder="Например: 2254" /></label>
        <label><span>Корпус</span><select value={searchFilters.building} onChange={event => setSearchFilters({...searchFilters, building: event.target.value})}><option value="">Все корпуса</option>{[...new Set(items.map(item => item.building).filter(Boolean))].map(value => <option key={value} value={value}>{value}</option>)}</select></label>
        <label><span>Тип мероприятия</span><select value={searchFilters.type} onChange={event => setSearchFilters({...searchFilters, type: event.target.value})}><option value="">Все типы</option>{[...new Set(items.map(item => item.event_format || item.booking_type).filter(Boolean))].map(value => <option key={value} value={value}>{value}</option>)}</select></label>
        <label><span>Период проведения</span><input type="month" value={searchFilters.period} onChange={event => setSearchFilters({...searchFilters, period: event.target.value})} /></label>
        </div>
      </section>
      <div className="user-booking-workspace">
      <aside className="user-booking-folders" aria-label="Папки моих заявок">
        <span className="user-booking-folders-title">Мои папки <button type="button" onClick={addUserFolder} aria-label="Создать папку"><Plus /></button></span>
        {[
          ["all", "Все мои заявки", items.length],
          ["active", "В работе", items.filter((item) => ["pending", "in_progress"].includes(item.status)).length],
          ["approved", "Подтверждённые", items.filter((item) => item.status === "approved").length],
          ["archive", "Архив", items.filter((item) => Boolean(item.archived_at) || folderAssignments[item.id] === "__archive").length],
        ].map(([value, label, count]) => (
          <button
            type="button"
            className={filter === value ? "active" : ""}
            onClick={() => setFilter(value)}
            key={value}
          >
            <span><Folder />{label}</span><b>{count}</b>
          </button>
        ))}
        {customFolders.map(folder => (
          <button type="button" className={filter === folder.id ? "active" : ""} onClick={() => setFilter(folder.id)} onDragOver={event => event.preventDefault()} onDrop={() => assignToFolder(folder.id)} key={folder.id}>
            <span><Folder />{folder.name}</span><b>{items.filter(item => folderAssignments[item.id] === folder.id).length}</b>
          </button>
        ))}
      </aside>
      <div className="user-booking-results">
      <div className="user-booking-results-toolbar"><h3>{filter === "all" ? "Все бронирования" : filter === "active" ? "В работе" : filter === "approved" ? "Подтверждённые" : filter === "archive" ? "Архив" : customFolders.find(folder => folder.id === filter)?.name || "Мои бронирования"}</h3><div><select aria-label="Период списка"><option>Все даты</option></select><b>Всего заявок: {filtered.length}</b></div></div>
      <div className="user-booking-table-head"><span>Статус</span><span>Мероприятие</span><span>Дата начала</span><span>Дата окончания</span><span>Ответственный</span><span>Дата подачи</span><span /></div>
      {loading ? (
        <div className="user-history-empty">Загрузка…</div>
      ) : filtered.length ? (
        <div className="user-history-list">
          {filtered.map((item) => {
            const status = (item.review_expired
              ? {
                  label: "Не подтверждена · просрочена",
                  hint: "Срок рассмотрения истёк",
                  tone: "rejected",
                }
              : STATUS[item.status]) || {
              label: item.status,
              hint: "",
              tone: item.status,
            };
            const entries = item.series_items || [item];
            const ids = entries.flatMap((entry) => [
              entry.id,
              ...(entry.set_extras || []).map((extra) => extra.id),
            ]);
            const series = entries.length > 1;
            const dates = [...new Set(entries.map((entry) => entry.date))];
            const roomNumbers = [
              ...new Set(entries.map((entry) => entry.room_number)),
            ];
            const buildingNames = [
              ...new Set(entries.map((entry) => entry.building)),
            ];
            return (
              <article
                id={`user-booking-${item.id}`}
                data-booking-ids={ids.join(" ")}
                draggable
                role="button"
                tabIndex={0}
                onClick={() => setDetail(item)}
                onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setDetail(item); } }}
                onContextMenu={event => openContextMenu(event, item)}
                onDragStart={() => setDraggedBooking(String(item.id))}
                onDragEnd={() => setDraggedBooking(null)}
                className={`request-card tone-${status.tone} ${ids.includes(highlighted) ? "booking-focus-highlight" : ""}`}
                key={item.id}
              >
                <header className="request-card-top">
                  <em className={`status ${status.tone}`}>{status.label}</em>
                  {item.set_extras?.length > 0 && (
                    <span className="room-set-badge">
                      Комплект · {item.set_extras.length + 1} ауд.
                    </span>
                  )}
                  {item.parent_booking_id && (
                    <span className="room-set-badge">
                      Дополнительная аудитория
                    </span>
                  )}
                  {series && (
                    <span className="request-series-chip">
                      <CalendarCheck />
                      Серия · {dates.length}{" "}
                      {plural(dates.length, "дата", "даты", "дат")}
                    </span>
                  )}
                </header>
                <ReviewDeadline item={item} />
                <h3 title={item.title}>{item.title}</h3>
                <div className="user-booking-row-data"><span>{cleanDate(item.date)}</span><span>{cleanDate(item.series_dates?.[1] || item.date_end || item.date)}</span><span>{item.customer_name || item.booked_by || "—"}</span><span>{item.created_at ? new Date(item.created_at).toLocaleDateString("ru-RU") : "—"}</span></div>
                <div className="user-booking-tags" onClick={event => event.stopPropagation()}>{(tags[item.id] || []).map(tag => <em data-color={/важно/i.test(tag) ? "peach" : /дпп/i.test(tag) ? "purple" : "blue"} key={tag}>{tag}</em>)}</div>
                <button type="button" className={`user-booking-favorite ${favorites[item.id] ? "active" : ""}`} aria-label={favorites[item.id] ? "Убрать из избранного" : "Добавить в избранное"} onClick={event => { event.stopPropagation(); toggleFavorite(item.id); }}><Star fill={favorites[item.id] ? "currentColor" : "none"} /></button>
                <ul className="request-facts">
                  <li>
                    <CalendarCheck />
                    <span>
                      <b>
                        {series
                          ? dateRange(dates[0], dates[dates.length - 1])
                          : cleanDate(item.date)}
                      </b>
                      <small>
                        {series
                          ? `${dates.length} ${plural(dates.length, "дата", "даты", "дат")} в серии`
                          : weekdayOf(item.date, "long")}
                      </small>
                    </span>
                  </li>
                  {!item.set_extras?.length && (
                    <li>
                      <MapPin />
                      <span>
                        <b>
                          {roomNumbers.length === 1
                            ? `Аудитория ${roomNumbers[0]}`
                            : `Аудитории ${roomNumbers.join(", ")}`}
                        </b>
                        <small>{buildingNames.join(", ")}</small>
                      </span>
                    </li>
                  )}
                  <li>
                    <Users />
                    <span>
                      <b>
                        {item.participants
                          ? `${item.participants} ${plural(item.participants, "участник", "участника", "участников")}`
                          : "Участники не указаны"}
                      </b>
                      <small>
                        Подразделение: {item.department_name || "не указано"}
                      </small>
                    </span>
                  </li>
                </ul>
                {series && (
                  <div className="request-dates" aria-label="Даты серии">
                    {dates.slice(0, 14).map((day) => {
                      const off = entries
                        .filter((entry) => entry.date === day)
                        .every(
                          (entry) =>
                            CLOSED.includes(entry.status) &&
                            entry.status !== "completed",
                        );
                      return (
                        <span
                          className={
                            off && !CLOSED.includes(item.status) ? "off" : ""
                          }
                          title={
                            off && !CLOSED.includes(item.status)
                              ? "Эта дата отменена или отклонена"
                              : cleanDate(day)
                          }
                          key={day}
                        >
                          <small>{weekdayOf(day, "short")}</small>
                          <b>{new Date(`${day}T00:00:00`).getDate()}</b>
                          <small>{monthShort(day)}</small>
                        </span>
                      );
                    })}
                    {dates.length > 14 && (
                      <span className="more">
                        <b>+{dates.length - 14}</b>
                      </span>
                    )}
                  </div>
                )}
                {item.status === "approved" && item.decided_by && (
                  <p className="request-note approved">
                    <ShieldCheck />
                    <span>
                      Подтвердил(а) <b>{item.decided_by}</b>
                      {item.decision_at
                        ? ` · ${new Date(item.decision_at).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" })}`
                        : ""}
                    </span>
                  </p>
                )}
                {item.status === "rejected" && (
                  <p className="request-note rejected">
                    <AlertCircle />
                    <span>
                      <b>Причина отказа:</b>{" "}
                      {item.decision_reason || "не указана"}
                    </span>
                  </p>
                )}
                {item.cancellation_reason && (
                  <p className="request-note rejected">
                    <AlertCircle />
                    <span>
                      <b>Причина отмены:</b> {item.cancellation_reason}
                      {item.cancellation_comment
                        ? ` — ${item.cancellation_comment}`
                        : ""}
                    </span>
                  </p>
                )}
                <RoomSetCards
                  main={item}
                  extras={item.set_extras || []}
                  actions={(extra) =>
                    canCancelEntry(extra) && (
                      <button
                        className="danger-link"
                        onClick={() => cancel(extra)}
                      >
                        Отменить
                      </button>
                    )
                  }
                />
                <AttachmentList
                  compact
                  items={[
                    ...new Map(
                      entries
                        .flatMap((entry) => entry.attachments || [])
                        .map((file) => [file.id, file]),
                    ).values(),
                  ]}
                  request={request}
                  user={user}
                  onChanged={reload}
                  replace
                />
                <FileReplacementHistory entries={entries} />
                <BookingChatLink item={item} />
                <footer className="request-card-foot">
                  {item.created_at && (
                    <small
                      title={new Date(item.created_at).toLocaleString("ru-RU", {
                        hour12: false,
                      })}
                    >
                      Создана{" "}
                      {new Date(item.created_at).toLocaleString("ru-RU", {
                        day: "2-digit",
                        month: "2-digit",
                        hour: "2-digit",
                        minute: "2-digit",
                        hour12: false,
                      })}
                    </small>
                  )}
                  {entries.some(canCancelEntry) && (
                    <button
                      className="danger-link"
                      onClick={() => {
                        if (entries.some(entry => entry.status === "approved")) {
                          window.alert("Удаление недоступно: заявка уже подтверждена. Для уточнения информации свяжитесь со Светланой Жуковой: +7 917 170 36 60, zhukova-sv@ranepa.ru");
                          return;
                        }
                        cancel(item);
                      }}
                    >
                      {entries.some(entry => entry.status === "approved") ? "Удалить бронь" : (series ? "Отменить серию" : "Отменить заявку")}
                    </button>
                  )}
                </footer>
              </article>
            );
          })}
        </div>
      ) : (
        <div className="user-history-empty">
          <History />
          <b>В этой категории заявок нет</b>
        </div>
      )}
      </div>
      </div>
      {contextMenu && (() => {
        const item = contextMenu.item;
        const submenuX = contextMenu.x + 620 < window.innerWidth ? contextMenu.x + 306 : Math.max(10, contextMenu.x - 326);
        const closeMenu = () => { setContextMenu(null); setContextPanel(null); };
        const moveTo = folderId => { const next = {...folderAssignments, [item.id]: folderId}; setFolderAssignments(next); saveUserState(customFolders, next, tags); closeMenu(); };
        return <>
          <div className="mw-context-menu user-request-context" style={{left: contextMenu.x, top: contextMenu.y}} role="menu">
            <button type="button" onClick={() => toggleFavorite(item.id)}><Star size={16} fill={favorites[item.id] ? "currentColor" : "none"}/>{favorites[item.id] ? "Убрать из избранного" : "Добавить в избранное"}</button>
            <button type="button" onClick={() => setContextPanel(contextPanel === "tags" ? null : "tags")}><Hash size={16}/>Добавить хэштег<ChevronRight className="mw-menu-chevron" size={16}/></button>
            <button type="button" onClick={() => setContextPanel(contextPanel === "folder" ? null : "folder")}><FolderInput size={16}/>Перенести в папку<ChevronRight className="mw-menu-chevron" size={16}/></button>
            <hr/>
            <button type="button" onClick={() => { setDetail(item); closeMenu(); }}><Eye size={16}/>Просмотреть детали</button>
            <button type="button" onClick={() => moveTo("__archive")}><Archive size={16}/>Перенести в архив</button>
            <button type="button" className="danger" onClick={() => { closeMenu(); if (item.status === "approved") { window.alert("Удаление недоступно: заявка уже подтверждена. Для уточнения информации свяжитесь со Светланой Жуковой: +7 917 170 36 60, zhukova-sv@ranepa.ru"); } else cancel(item); }}><Trash2 size={16}/>Удалить</button>
          </div>
          {contextPanel === "tags" && <div className="user-request-submenu" style={{left: submenuX, top: Math.max(10, contextMenu.y + 35)}}>
            <label>Теги<input autoFocus value={tagDraft} onChange={event => setTagDraft(event.target.value)} onKeyDown={event => { if (event.key === "Enter") { event.preventDefault(); addTagValue(item.id, tagDraft); } }} placeholder="Найти или создать тег"/></label>
            <div>{[...new Set(Object.values(tags).flat())].map(tag => <button type="button" key={tag} onClick={() => addTagValue(item.id, tag)}>{tag}</button>)}</div>
            {tagDraft.trim() && <button type="button" className="create" onClick={() => addTagValue(item.id, tagDraft)}>＋ Создать «{tagDraft.trim()}»</button>}
          </div>}
          {contextPanel === "folder" && <div className="user-request-submenu user-folder-submenu" style={{left: submenuX, top: Math.max(10, contextMenu.y + 70)}}><button type="button" onClick={() => moveTo(null)}>Без папки</button>{customFolders.map(folder => <button type="button" onClick={() => moveTo(folder.id)} key={folder.id}><Folder size={15}/>{folder.name}</button>)}</div>}
        </>;
      })()}
      {detail && <div className="center-modal"><button className="center-backdrop" onClick={() => setDetail(null)}/><aside className="booking-detail-panel user-booking-detail-panel"><header><div><small>ЗАЯВКА № {detail.external_reference || detail.id}</small><h2>{detail.title}</h2></div><button type="button" className="icon" onClick={() => setDetail(null)}><X/></button></header>
        <section><h3>Основная информация</h3><div className="user-detail-grid"><div><small>Статус</small><b>{STATUS[detail.status]?.label || detail.status}</b></div><div><small>Период проведения</small><b>{cleanDate(detail.date)} — {cleanDate(detail.series_dates?.[1] || detail.date_end || detail.date)}</b></div><div><small>Аудитория</small><b>{detail.building || "—"} · ауд. {detail.room_number || "—"}</b></div><div><small>Ответственный</small><b>{detail.customer_name || detail.booked_by || "—"}</b></div><div><small>Подразделение</small><b>{detail.department_name || "—"}</b></div><div><small>Участники</small><b>{detail.participants || "—"}</b></div><div><small>Формат мероприятия</small><b>{detail.event_format || detail.booking_type || "—"}</b></div><div><small>Дата подачи</small><b>{detail.created_at ? new Date(detail.created_at).toLocaleDateString("ru-RU") : "—"}</b></div></div></section>
        {detail.comment && <section><h3>Комментарий</h3><p>{detail.comment}</p></section>}
        <section><BookingChatLink item={detail}/></section>
        <section><AttachmentList compact items={(detail.series_items || [detail]).flatMap(entry => entry.attachments || [])} request={request} user={user} onChanged={reload} replace/></section>
      </aside></div>}
    </section>
  );
}

function UserCancelDialog({ item, request, close, done }) {
  const targets = (item.series_items || [item]).filter(canCancelEntry);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const submit = async (event) => {
    event.preventDefault();
    setSaving(true);
    const data = Object.fromEntries(new FormData(event.currentTarget));
    const body = JSON.stringify({
      reason: data.reason,
      comment: data.comment,
      replacement_offered: false,
      notify_customer: false,
    });
    try {
      if (item.series_items)
        await request(`/api/me/booking-series/${item.series_id}/cancel`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body,
        });
      else
        await request(`/api/me/bookings/${item.id}/cancel`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body,
        });
      done();
    } catch (failure) {
      setError(failure.message);
      setSaving(false);
    }
  };
  return (
    <div className="modal">
      <button className="backdrop" onClick={close} />
      <form className="user-cancel-dialog" onSubmit={submit}>
        <header>
          <div>
            <small>ОТМЕНА С СОХРАНЕНИЕМ ИСТОРИИ</small>
            <h2>{item.series_items ? "Отменить серию" : "Отменить заявку"}</h2>
          </div>
          <button type="button" className="icon" onClick={close}>
            <X />
          </button>
        </header>
        {item.series_items ? (
          <p>
            Серия бронирований: будет отменено записей — {targets.length}
            <br />
            {formatDate(item.series_dates[0])} —{" "}
            {formatDate(item.series_dates[1])}
          </p>
        ) : (
          <p>
            {item.building} · аудитория {item.room_number}
            <br />
            {formatDate(item.date)}
          </p>
        )}
        {item.set_extras?.length > 0 && (
          <p>
            <b>
              При отмене основной аудитории также будут отменены дополнительные
              аудитории комплекта, если их ещё можно отменить.
            </b>
          </p>
        )}
        <label>
          <span>Причина отмены</span>
          <select name="reason" required>
            <option value="">Выберите причину</option>
            <option>Изменились планы</option>
            <option>Мероприятие перенесено</option>
            <option>Аудитория больше не требуется</option>
            <option>Ошибка в параметрах заявки</option>
            <option>Другая причина</option>
          </select>
        </label>
        <label>
          <span>Комментарий</span>
          <textarea
            name="comment"
            required
            minLength="2"
            placeholder="Уточните обстоятельства отмены"
          />
        </label>
        {error && <p className="error">{error}</p>}
        <footer>
          <button type="button" className="secondary" onClick={close}>
            Вернуться
          </button>
          <button className="soft-danger" disabled={saving}>
            {saving ? "Сохраняем…" : "Подтвердить отмену"}
          </button>
        </footer>
      </form>
    </div>
  );
}
import { BookingChatLink } from "./Chat";
