"""Job Journal - Interview your career, customize your resume."""

__version__ = "0.1.0"

from jj.autofill import (
    ATSType,
    detect_ats,
    get_ats_config,
    load_profile_data,
    build_field_list,
    get_answer_for_question,
    generate_interest_paragraph,
)
