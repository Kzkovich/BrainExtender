# {{ title }}

**Дата:** {{ date }}
**Респондент:** {{ respondent or 'аноним' }}
**Воркспейс:** {{ workspace }}

## Ключевые инсайты
{% for insight in insights %}
- {{ insight }}
{% else %}
_нет_
{% endfor %}

## Цитаты
{{ quotes or '_нет_' }}

## Наблюдения
{{ observations }}
