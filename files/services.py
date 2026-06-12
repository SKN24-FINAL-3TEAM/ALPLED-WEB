from django.db.models import Q

from common.models import Code


FILE_TYPE_SEQUENCE = ("FILE_RFP", "FILE_MEETING")
LEGACY_FILE_TYPE_ALIASES = {
    "RFP": "FILE_RFP",
    "MEETING": "FILE_MEETING",
}

SEARCH_FIELD_CHOICES = (
    ("all", "전체"),
    ("creator", "등록자"),
    ("name", "문서명"),
)


def _get_ordered_codes(code_values):
    code_map = Code.objects.in_bulk(code_values, field_name="code")
    return [code_map[code] for code in code_values if code in code_map]


def get_file_type_choices(*, include_all=True, allowed_codes=None):
    target_codes = allowed_codes or FILE_TYPE_SEQUENCE
    choices = [("all", "전체")] if include_all else []
    for code in _get_ordered_codes(target_codes):
        choices.append((code.code, code.name))
    return tuple(choices)


def apply_file_filters(params, queryset, *, default_file_type="all", allowed_file_types=None):
    file_type = params.get("file_type", default_file_type)
    file_type = LEGACY_FILE_TYPE_ALIASES.get(file_type, file_type)
    search_field = params.get("field", "all")
    query = params.get("q", "").strip()

    if allowed_file_types:
        queryset = queryset.filter(file_type_id__in=allowed_file_types)
        valid_values = {"all", *allowed_file_types}
        if file_type not in valid_values:
            file_type = default_file_type

    if file_type != "all":
        queryset = queryset.filter(file_type_id=file_type)

    if query:
        if search_field == "creator":
            queryset = queryset.filter(created_by__name__icontains=query)
        elif search_field == "name":
            queryset = queryset.filter(name__icontains=query)
        else:
            queryset = queryset.filter(
                Q(created_by__name__icontains=query) | Q(name__icontains=query)
            )

    return queryset, file_type, search_field, query


def build_project_file_rows(queryset):
    rows = []
    for index, document in enumerate(queryset, start=1):
        rows.append(
            {
                "sn": document.sn,
                "display_no": index,
                "name": document.name,
                "type_name": getattr(document.file_type, "name", "-"),
                "creator_name": getattr(document.created_by, "name", "-") or "-",
                "created_at": document.created_at,
            }
        )
    return rows
