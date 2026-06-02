# {{ title }}

**Дата:** {{ date }}
**Воркспейс:** {{ workspace }}
**Статус:** {{ status or 'active' }}

## Гипотеза
Если **{{ condition }}**, то **{{ expected_outcome }}**, потому что **{{ rationale }}**.

## Как проверить
{{ validation_method or '_не определено_' }}

## Результат проверки
{{ result or '_ещё не проверяли_' }}
