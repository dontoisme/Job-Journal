"""Job Journal - Interview your career, customize your resume."""

__version__ = "0.1.0"

from jj.autofill import (  # noqa: F401
    ATSType,
    build_field_list,
    detect_ats,
    generate_interest_paragraph,
    get_answer_for_question,
    get_ats_config,
    load_profile_data,
)
