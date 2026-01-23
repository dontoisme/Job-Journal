"""Playwright auto-fill module for job applications.

Provides ATS detection and field mapping for automated form filling.
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional
import re

from jj.config import load_profile


class ATSType(Enum):
    """Known ATS platforms."""
    ASHBY = "ashby"
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    WORKDAY = "workday"
    ICIMS = "icims"
    RIPPLING = "rippling"
    SMARTRECRUITERS = "smartrecruiters"
    BAMBOOHR = "bamboohr"
    UNKNOWN = "unknown"


@dataclass
class ATSConfig:
    """Configuration for a specific ATS platform."""
    ats_type: ATSType
    name_field: str
    email_field: str
    phone_field: str
    linkedin_field: Optional[str]
    resume_upload_selector: Optional[str]
    location_field: Optional[str]
    # For toggle questions (work auth, etc.)
    yes_button_pattern: Optional[str] = None
    no_button_pattern: Optional[str] = None
    submit_button: Optional[str] = None


# ATS URL patterns
ATS_PATTERNS: dict[str, ATSType] = {
    r"jobs\.ashbyhq\.com": ATSType.ASHBY,
    r"boards\.greenhouse\.io": ATSType.GREENHOUSE,
    r"\.greenhouse\.io": ATSType.GREENHOUSE,
    r"jobs\.lever\.co": ATSType.LEVER,
    r"\.myworkdayjobs\.com": ATSType.WORKDAY,
    r"icims\.com": ATSType.ICIMS,
    r"ats\.rippling\.com": ATSType.RIPPLING,
    r"jobs\.smartrecruiters\.com": ATSType.SMARTRECRUITERS,
    r"bamboohr\.com": ATSType.BAMBOOHR,
}


# ATS-specific field configurations
ATS_CONFIGS: dict[ATSType, ATSConfig] = {
    ATSType.ASHBY: ATSConfig(
        ats_type=ATSType.ASHBY,
        name_field="Full Name",
        email_field="Email",
        phone_field="Phone",
        linkedin_field="LinkedIn",
        resume_upload_selector='input[type="file"]',
        location_field=None,
        yes_button_pattern="Yes",
        no_button_pattern="No",
        submit_button="Submit Application",
    ),
    ATSType.GREENHOUSE: ATSConfig(
        ats_type=ATSType.GREENHOUSE,
        name_field="Full name",
        email_field="Email",
        phone_field="Phone",
        linkedin_field="LinkedIn profile",
        resume_upload_selector='input[type="file"]',
        location_field="Location",
        submit_button="Submit Application",
    ),
    ATSType.LEVER: ATSConfig(
        ats_type=ATSType.LEVER,
        name_field="Full name",
        email_field="Email",
        phone_field="Phone",
        linkedin_field="LinkedIn URL",
        resume_upload_selector='input[type="file"]',
        location_field=None,
        submit_button="Submit application",
    ),
    ATSType.RIPPLING: ATSConfig(
        ats_type=ATSType.RIPPLING,
        name_field="Full Name",
        email_field="Email",
        phone_field="Phone",
        linkedin_field="LinkedIn",
        resume_upload_selector='input[type="file"]',
        location_field="State",
        yes_button_pattern="Yes",
        no_button_pattern="No",
        submit_button="Submit",
    ),
    ATSType.WORKDAY: ATSConfig(
        ats_type=ATSType.WORKDAY,
        name_field="Legal Name",
        email_field="Email Address",
        phone_field="Phone Number",
        linkedin_field="LinkedIn",
        resume_upload_selector='input[type="file"]',
        location_field="Country",
        submit_button="Submit",
    ),
}


def detect_ats(url: str) -> ATSType:
    """Detect ATS type from URL."""
    for pattern, ats_type in ATS_PATTERNS.items():
        if re.search(pattern, url, re.IGNORECASE):
            return ats_type
    return ATSType.UNKNOWN


def get_ats_config(ats_type: ATSType) -> Optional[ATSConfig]:
    """Get configuration for an ATS type."""
    return ATS_CONFIGS.get(ats_type)


@dataclass
class ProfileData:
    """Extracted profile data for form filling."""
    full_name: str
    first_name: str
    last_name: str
    preferred_name: str
    email: str
    phone: str
    location: str
    linkedin: str
    github: Optional[str]
    portfolio: Optional[str]
    work_auth: str
    requires_sponsorship: bool
    years_experience: int
    current_title: str
    current_company: str
    pronouns: str
    willing_to_relocate: str


def load_profile_data() -> ProfileData:
    """Load profile data from the profile.yaml file."""
    profile = load_profile()

    name = profile.get("name", {})
    contact = profile.get("contact", {})
    links = profile.get("links", {})
    defaults = profile.get("defaults", {})

    first_name = name.get("first", "")
    last_name = name.get("last", "")

    return ProfileData(
        full_name=f"{first_name} {last_name}".strip(),
        first_name=first_name,
        last_name=last_name,
        preferred_name=name.get("preferred", first_name),
        email=contact.get("email", ""),
        phone=contact.get("phone", ""),
        location=contact.get("location", ""),
        linkedin=links.get("linkedin", ""),
        github=links.get("github"),
        portfolio=links.get("portfolio"),
        work_auth=profile.get("work_authorization", ""),
        requires_sponsorship=profile.get("defaults", {}).get("requires_sponsorship", "No") == "Yes",
        years_experience=profile.get("years_experience", 0),
        current_title=profile.get("current_title", ""),
        current_company=profile.get("current_company", ""),
        pronouns=defaults.get("pronouns", ""),
        willing_to_relocate=defaults.get("willing_to_relocate", "Yes"),
    )


@dataclass
class FormField:
    """Represents a form field to fill."""
    label: str
    value: str
    field_type: str = "text"  # text, select, radio, checkbox, file
    ref: Optional[str] = None  # Playwright element ref


def build_field_list(profile: ProfileData, ats_type: ATSType) -> list[FormField]:
    """Build list of fields to fill based on ATS type and profile."""
    fields = [
        FormField(label="Full Name", value=profile.full_name, field_type="text"),
        FormField(label="Email", value=profile.email, field_type="text"),
        FormField(label="Phone", value=profile.phone, field_type="text"),
    ]

    if profile.linkedin:
        fields.append(FormField(label="LinkedIn", value=profile.linkedin, field_type="text"))

    # ATS-specific fields
    if ats_type == ATSType.ASHBY:
        if profile.preferred_name:
            fields.append(FormField(label="Preferred Name", value=profile.preferred_name, field_type="text"))

    return fields


# Common work authorization answers
WORK_AUTH_ANSWERS: dict[str, dict[str, str]] = {
    "us_authorized": {
        "Are you authorized to work in the United States": "Yes",
        "Are you legally authorized to work in the United States": "Yes",
        "Do you have the legal right to work in the United States": "Yes",
        "authorized to work in the US": "Yes",
        "legally authorized to work": "Yes",
        "work authorization": "Authorized",
        "employment eligibility": "Yes",
    },
    "sponsorship": {
        "Will you now or in the future require sponsorship": "No",
        "Do you require sponsorship": "No",
        "require visa sponsorship": "No",
        "need sponsorship": "No",
        "sponsorship for employment visa": "No",
        "require any type of visa sponsorship": "No",
    },
    "relocate": {
        "willing to relocate": "Yes",
        "open to relocation": "Yes",
        "consider relocating": "Yes",
    },
    "prior_employee": {
        "previously employed": "No",
        "former employee": "No",
        "worked at": "No",
        "prior employee": "No",
    },
}


def match_question(question_text: str, answers: dict[str, str]) -> Optional[str]:
    """Match a question to a predefined answer."""
    question_lower = question_text.lower()
    for pattern, answer in answers.items():
        if pattern.lower() in question_lower:
            return answer
    return None


def get_answer_for_question(question_text: str, profile: ProfileData) -> Optional[str]:
    """Get answer for a common application question."""
    # Check each category of answers
    for category, answers in WORK_AUTH_ANSWERS.items():
        matched = match_question(question_text, answers)
        if matched:
            # Override based on profile for sponsorship
            if category == "sponsorship" and profile.requires_sponsorship:
                return "Yes"
            return matched

    # Location-based questions
    question_lower = question_text.lower()
    if "state" in question_lower and "united states" in question_lower:
        # Extract state from location
        if profile.location:
            parts = profile.location.split(",")
            if len(parts) >= 2:
                return parts[1].strip()

    if "currently based in" in question_lower and "united states" in question_lower:
        return "Yes" if "TX" in profile.location or "US" in profile.work_auth else None

    return None


# Field label variations for different ATS platforms
FIELD_ALIASES: dict[str, list[str]] = {
    "full_name": ["Full Name", "Name", "Full legal name", "Legal name", "Your name"],
    "first_name": ["First Name", "First", "Given Name"],
    "last_name": ["Last Name", "Last", "Surname", "Family Name"],
    "email": ["Email", "Email Address", "E-mail", "Email*"],
    "phone": ["Phone", "Phone Number", "Mobile", "Mobile Phone", "Contact Number"],
    "linkedin": ["LinkedIn", "LinkedIn URL", "LinkedIn Profile", "LinkedIn profile URL"],
    "location": ["Location", "City", "Current Location", "Where are you based"],
    "resume": ["Resume", "Resume/CV", "Upload Resume", "Attach Resume"],
}


def normalize_field_label(label: str) -> Optional[str]:
    """Normalize a field label to a standard key."""
    label_lower = label.lower().strip()
    for key, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if alias.lower() in label_lower:
                return key
    return None


def get_profile_value(key: str, profile: ProfileData) -> Optional[str]:
    """Get profile value for a normalized field key."""
    mapping = {
        "full_name": profile.full_name,
        "first_name": profile.first_name,
        "last_name": profile.last_name,
        "email": profile.email,
        "phone": profile.phone,
        "linkedin": profile.linkedin,
        "location": profile.location,
    }
    return mapping.get(key)


# Interest paragraph templates by company/domain
INTEREST_TEMPLATES: dict[str, str] = {
    "health": """I'm drawn to {company}'s mission in healthcare technology. At Wellcore, I built a fully integrated virtual care platform serving 51 states, including EHR integration, provider scheduling, and pharmacy fulfillment. I understand the complexity of healthcare systems and the importance of patient-centered design.""",

    "ai": """I'm excited about {company}'s work in AI and automation. Most recently, I led the launch of a multi-agent AI orchestration system with 5 specialized agents that independently interpret user intent and execute tasks autonomously. I thrive in environments pushing the boundaries of what's possible with AI.""",

    "growth": """I'm drawn to {company}'s growth trajectory and product-led approach. At ZenBusiness, I built self-serve acquisition funnels driving 8% conversion lift (~1,500 new customers/day) and scaled experimentation velocity 250%. I love the intersection of product and growth.""",

    "default": """I'm excited about this opportunity at {company}. With 12+ years in product management spanning B2B SaaS, health-tech, and AI, I bring a track record of shipping products that drive measurable business outcomes. I'd love to bring this experience to your team.""",
}


def generate_interest_paragraph(company: str, keywords: list[str]) -> str:
    """Generate an interest paragraph based on company and role keywords."""
    # Match keywords to templates
    keywords_lower = [k.lower() for k in keywords]

    if any(k in keywords_lower for k in ["health", "healthcare", "medical", "patient", "clinical"]):
        template = INTEREST_TEMPLATES["health"]
    elif any(k in keywords_lower for k in ["ai", "ml", "agent", "automation", "llm"]):
        template = INTEREST_TEMPLATES["ai"]
    elif any(k in keywords_lower for k in ["growth", "plg", "acquisition", "retention", "funnel"]):
        template = INTEREST_TEMPLATES["growth"]
    else:
        template = INTEREST_TEMPLATES["default"]

    return template.format(company=company)
