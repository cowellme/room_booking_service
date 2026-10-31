export const BOOKING_TYPE_LABELS = {
  lecture: 'Лекция', seminar: 'Семинар', meeting: 'Совещание', lab: 'Лабораторное занятие',
  office: 'Встреча', service: 'Служебная блокировка', other: 'Другое',
};

// Mirrors EQUIPMENT_PATTERNS in backend/app/services/availability.py: the same
// patterns in the same order, and one item may fall into several categories.
// JavaScript's \b ignores Cyrillic, so short Cyrillic words use explicit lookarounds.
const EQUIPMENT_RULES = [
  [/видеостен|\bled\b/, 'Видеостена'],
  [/колонк|акустическ|звукоусил/, 'Колонки'],
  [/компьютер|ноутбук|моноблок|\bmac\b|(?<![а-яёa-z0-9])пк(?![а-яёa-z0-9])/, 'Компьютер'],
  [/проектор/, 'Проектор'], [/микрофон/, 'Микрофон'],
  [/видеокамер|(?<!контент-)(?<!контент )камера/, 'Видеокамера'],
  [/видеосвяз|вкс|polycom/, 'Видеосвязь'],
  [/телевизор|монитор|(?<![а-яёa-z0-9])тв(?![а-яёa-z0-9])/, 'Монитор или телевизор'],
  [/принтер|мфу/, 'Принтер или МФУ'],
  [/интерактивн.*доск/, 'Интерактивная доска'], [/маркерн.*доск/, 'Маркерная доска'],
  [/флипчарт/, 'Флипчарт'], [/конгресс/, 'Конгресс-система'],
  [/синхронн.*перевод/, 'Система синхронного перевода'],
  [/светов/, 'Световое оборудование'],
  [/контент.?камер/, 'Контент-камера'],
];

const EQUIPMENT_CATEGORY_LABELS = new Set(EQUIPMENT_RULES.map(([, label]) => label));

// Things that are brought to a room on request and are not part of its fixed equipment.
export const CONSUMABLE_EQUIPMENT = ['Мел', 'Маркеры', 'Вода', 'Стикеры', 'Блокноты', 'Ручки', 'Кликер'];

export function equipmentCategoriesOf(value = '') {
  const normalized = value.toLowerCase();
  return EQUIPMENT_RULES.filter(([pattern]) => pattern.test(normalized)).map(([, label]) => label);
}

export function simplifyEquipment(value = '') {
  return equipmentCategoriesOf(value)[0] || null;
}

export function roomEquipmentCategories(room) {
  return [...new Set((room.equipment || []).flatMap(equipmentCategoriesOf))];
}

export const isEquipmentCategory = value => EQUIPMENT_CATEGORY_LABELS.has(value);

// Only categories describe what a room has, so only they can narrow the room search.
export const equipmentSearchFilter = values => values.filter(isEquipmentCategory);

export function additionalEquipmentOptions(rooms = []) {
  const categories = [...new Set(rooms.flatMap(roomEquipmentCategories))].sort((a, b) => a.localeCompare(b, 'ru'));
  return [...categories, ...CONSUMABLE_EQUIPMENT.filter(item => !categories.includes(item))];
}
