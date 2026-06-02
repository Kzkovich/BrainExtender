# {{ title }}

**Дата:** {{ date }}
**Участники:** {{ people | join(', ') if people else 'не указано' }}

## Суть
{{ narrative }}

## Решения и договорённости
{% for decision in key_decisions %}
- {{ decision }}
{% else %}
_нет_
{% endfor %}

## Задачи
{% for item in action_items %}
- [ ] {{ item.task }} — {{ item.owner or '?' }}
{% else %}
_нет_
{% endfor %}
