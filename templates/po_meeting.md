# {{ title }}

**Дата:** {{ date }}
**Участники:** {{ people | join(', ') if people else 'не указано' }}
**Воркспейс:** {{ workspace }}
**Фича:** {{ feature_slug or 'не привязано' }}

## Ключевые решения
{% for decision in key_decisions %}
- {{ decision }}
{% else %}
_нет_
{% endfor %}

## Договорённости
{{ agreements_section or '_нет_' }}

## Action items
{% for item in action_items %}
- [ ] {{ item.task }} — {{ item.owner or '?' }} — {{ item.deadline or 'без срока' }}
{% else %}
_нет_
{% endfor %}

## Контекст
{{ narrative }}
