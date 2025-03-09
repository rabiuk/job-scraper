import re
import logging

logger = logging.getLogger(__name__)

def extract_min_years(text):
    """Extract the minimum years of experience from a text string."""
    text = text.lower()
    min_years = []
    range_matches = re.findall(r'(\d+)-(\d*\+?)\s*years?', text)
    for start, end in range_matches:
        min_years.append(int(start))
    plus_matches = re.findall(r'(\d+)\+\s*years?|at least (\d+)\s*years?', text)
    for match in plus_matches:
        if match[0]:
            min_years.append(int(match[0]))
        elif match[1]:
            min_years.append(int(match[1]))
    standalone_matches = re.findall(r'(\d+)\s*years?', text)
    for match in standalone_matches:
        if int(match) not in min_years:
            min_years.append(int(match))
    return min(min_years) if min_years else 0

def is_entry_level(job, min_qual, pref_qual):
    title = job.get("postingTitle", "").lower()
    summary = job.get("jobSummary", "").lower()
    min_qual = min_qual.lower() if min_qual else ""
    pref_qual = pref_qual.lower() if pref_qual else ""

    # Define positive and negative indicators
    positive_keywords = ["junior", "associate"]  # Only unambiguous single words
    positive_phrases = [
        "entry level", "entry-level", "new grad", "recent graduate", "early career",
        "internship experience", "student", "beginner"
    ]
    negative_keywords = ["senior", "sr", "staff", "lead", "manager", "principal", "expert", "advanced"]

    # Check title and summary
    has_positive_title_summary = any(
        re.search(rf'\b{kw}\b', title) or re.search(rf'\b{kw}\b', summary)
        for kw in positive_keywords
    ) or any(
        phrase in title or phrase in summary for phrase in positive_phrases
    )
    has_negative_title_summary = any(
        re.search(rf'\b{kw}\b', title + " " + summary) 
        for kw in negative_keywords
    )

    logger.debug(f"Title: {title}")
    logger.debug(f"Summary: {summary}")
    logger.debug(f"Has positive keywords: {has_positive_title_summary}")
    logger.debug(f"Has negative keywords: {has_negative_title_summary} (matched: {[kw for kw in negative_keywords if re.search(rf'\b{kw}\b', title + ' ' + summary)]})")

    if has_negative_title_summary:
        logger.debug("Rejected due to negative keywords in title/summary")
        return False
    if has_positive_title_summary:
        logger.debug("Accepted due to positive keywords/phrases in title/summary")
        return True

    # Check qualifications
    has_positive_qual = any(
        re.search(rf'\b{kw}\b', min_qual) or re.search(rf'\b{kw}\b', pref_qual)
        for kw in positive_keywords
    ) or any(
        phrase in min_qual or phrase in pref_qual for phrase in positive_phrases
    )
    
    matched_keywords = [kw for kw in positive_keywords if re.search(rf'\b{kw}\b', min_qual) or re.search(rf'\b{kw}\b', pref_qual)]
    matched_phrases = [phrase for phrase in positive_phrases if phrase in min_qual or phrase in pref_qual]
    if has_positive_qual:
        logger.debug(f"Accepted due to positive keywords/phrases in qualifications: {matched_keywords + matched_phrases}")
        return True

    # Check experience requirement
    if min_qual:
        min_years = extract_min_years(min_qual)
        logger.debug(f"Min years extracted: {min_years}")
        has_zero_start_range = bool(re.search(r'\b0-\d*\+?\s*years?', min_qual))
        if has_zero_start_range:
            logger.debug("Found range starting at 0, accepting as entry-level")
            return True
        if min_years > 1:
            logger.debug(f"Rejecting: {min_years} years exceeds 0-1 threshold")
            return False
        if min_years in (0, 1):
            logger.debug(f"Accepting: {min_years} years within 0-1 threshold")
            return True

    logger.debug("No specific years or keywords, defaulting to no negative keywords check")
    return not has_negative_title_summary