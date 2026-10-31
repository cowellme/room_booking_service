-- Восстановление дат серий, которые система закрыла как «не рассмотрена до начала»,
-- хотя другая дата той же серии была подтверждена. Сначала посмотрите, что попадёт под изменение:
SELECT b.id, b.date, b.time_start, b.time_end, b.title, b.room_id, b.series_id
FROM bookings b
WHERE b.status = 'rejected'
  AND b.decision_reason = 'Заявка не была рассмотрена до начала мероприятия'
  AND b.series_id IS NOT NULL
  AND EXISTS (SELECT 1 FROM bookings o WHERE o.series_id = b.series_id AND o.status IN ('approved', 'completed'))
  AND NOT EXISTS (SELECT 1 FROM bookings c WHERE c.id <> b.id AND c.room_id = b.room_id AND c.date = b.date
                  AND c.status IN ('approved', 'completed') AND c.time_start < b.time_end AND c.time_end > b.time_start)
ORDER BY b.series_id, b.date;

-- Если список верный, выполните (прошедшие даты станут «Состоялось», будущие — «Подтверждено»):
BEGIN;
UPDATE bookings b
SET status = CASE WHEN b.date < CURRENT_DATE THEN 'completed' ELSE 'approved' END,
    decision_reason = NULL, updated_at = now()
WHERE b.status = 'rejected'
  AND b.decision_reason = 'Заявка не была рассмотрена до начала мероприятия'
  AND b.series_id IS NOT NULL
  AND EXISTS (SELECT 1 FROM bookings o WHERE o.series_id = b.series_id AND o.status IN ('approved', 'completed'))
  AND NOT EXISTS (SELECT 1 FROM bookings c WHERE c.id <> b.id AND c.room_id = b.room_id AND c.date = b.date
                  AND c.status IN ('approved', 'completed') AND c.time_start < b.time_end AND c.time_end > b.time_start);
COMMIT;
