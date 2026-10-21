"""Create an UNLABELED synthetic scaffold. Never overwrites existing annotations."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
target = root / 'data/evaluation/events.json'
if target.exists():
    raise SystemExit('Evaluation file already exists; preserve human annotations.')
topics = {
    'rates': ['Ключевая ставка сохранена', 'Изменились предложения кредитования', 'Компании пересматривают сроки рефинансирования', 'Доходность депозитов меняется', 'Фиксированные ставки обсуждаются рынком', 'Длинное финансирование становится доступнее', 'Условия оборотных кредитов обновлены'],
    'fx': ['Увеличены сроки трансграничных расчетов', 'Курс расчетной валюты изменился', 'Появился дополнительный маршрут платежей', 'Экспортеры пересматривают валюту контрактов', 'Импортные расчеты требуют новых документов', 'Расчеты в национальных валютах обсуждаются рынком'],
    'logistics': ['Грузовой терминал меняет расписание', 'Перевозки задерживаются на одном маршруте', 'Складские мощности расширены', 'Транспортный тариф пересмотрен', 'Новый портовый маршрут открыт', 'Поставки оборудования требуют большего срока'],
    'commodities': ['Цены на промышленное сырье изменились', 'Сталь дорожает на региональном рынке', 'Металлургические предприятия меняют графики', 'Стоимость энергоносителей снижается', 'Предложение цветных металлов расширяется', 'Запасы сырья на складах растут'],
    'demand': ['Спрос на базовые товары увеличился', 'Розничные продажи изменили динамику', 'Оптовая торговля сообщает о новых заказах', 'Потребление услуг замедляется', 'Покупатели смещаются в бюджетный сегмент', 'Промышленные заказы становятся сезонными'],
    'regulation': ['Опубликован проект новых правил отчетности', 'Обсуждается изменение пошлин', 'Уточнены требования к договорам', 'Предложено изменить налоговый учет', 'Регулятор выпустил разъяснение', 'Установлен переходный период для отчетности'],
    'labor': ['Дефицит технических кадров растет', 'Сроки найма специалистов увеличились', 'Работодатели пересматривают зарплаты', 'Обучение работников получает поддержку', 'Потребность в сезонных кадрах изменилась', 'Рынок труда стал менее напряженным'],
    'liquidity': ['Сезонные платежи сконцентрированы', 'Сроки оплаты контрагентов увеличились', 'Оборотный капитал требует пересмотра', 'Входящие платежи сдвинулись', 'Факторинг получил новые условия', 'Компании меняют платежный календарь', 'Ликвидность банковского сектора увеличилась'],
}
records = []
for topic, titles in topics.items():
    for title in titles:
        records.append({'id': f'eval-{len(records)+1:03}', 'title': title,
            'content': f'Синтетическая учебная публикация: {title.lower()}. Условия и применимость к конкретной компании требуют проверки по договорам, географии и доступным признакам.',
            'topics': [topic], 'synthetic': True})
assert len(records) == 50
# Interleave topics so both partitions contain varied themes. IDs are event identities.
records = sorted(records, key=lambda r: (int(r['id'].split('-')[1]) % 7, r['id']))
for i, record in enumerate(records):
    record['split'] = 'development' if i < 30 else 'holdout'
    record['relevance'] = {f'{company}:{role}': None for company in ['demo-metal','demo-retail','demo-logistics'] for role in ['CEO','CFO','TREASURER']}
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps({'status': 'synthetic_unlabeled', 'reviewer': None, 'reviewed_at': None, 'events': records}, ensure_ascii=False, indent=2), encoding='utf-8')
print('Created 30 development + 20 holdout synthetic events; labels require independent review.')
