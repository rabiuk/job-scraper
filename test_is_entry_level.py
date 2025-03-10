import unittest
from utils import is_entry_level
from setup_enviroment import setup_environment

setup_environment()
# To run this: python -m unittest test_is_entry_level.py

class TestIsEntryLevel(unittest.TestCase):

    def test_positive_keywords_in_title(self):
        job = {"postingTitle": "Junior Software Engineer", "jobSummary": "Looking for a junior developer."}
        min_qual = "Bachelor's degree in Computer Science."
        pref_qual = "Experience with Python."
        self.assertTrue(is_entry_level(job, min_qual, pref_qual))

    def test_negative_keywords_in_title(self):
        job = {"postingTitle": "Senior Software Engineer", "jobSummary": "Looking for a senior developer."}
        min_qual = "Bachelor's degree in Computer Science."
        pref_qual = "Experience with Python."
        self.assertFalse(is_entry_level(job, min_qual, pref_qual))

    def test_positive_phrases_in_summary(self):
        job = {"postingTitle": "Software Engineer", "jobSummary": "This is an entry-level position."}
        min_qual = "Bachelor's degree in Computer Science."
        pref_qual = "Experience with Python."
        self.assertTrue(is_entry_level(job, min_qual, pref_qual))

    def test_negative_keywords_in_summary(self):
        jobs = [
            {"postingTitle": "Software Engineer", "jobSummary": "This is a senior position."},
            {"postingTitle": "Software Engineer", "jobSummary": "This is a lead software engineer position."},
        ]
        min_qual = "Bachelor's degree in Computer Science."
        pref_qual = "Experience with Python."
        for job in jobs:
            self.assertFalse(is_entry_level(job, min_qual, pref_qual))

    def test_positive_keywords_in_min_qual(self):
        job = {"postingTitle": "Software Engineer", "jobSummary": "Looking for a developer."}
        positive_min_quals = [
            "Junior developer with 0-1 years of experience.",
            "Entry-level developer with 1 year of experience.",
            "New grad with 0 years of experience.",
            "Bachelors of Science in Computer Science with 0-3+ years of relevant confirmed experience",
            "Bachelors of Science in Computer Science with 1-3+ years of relevant confirmed experience",
        ]
        pref_qual = "Experience with Python."
        for min_qual in positive_min_quals:
            self.assertTrue(is_entry_level(job, min_qual, pref_qual))

    def test_negative_keywords_in_min_qual(self):
        job = {"postingTitle": "Software Engineer", "jobSummary": "Looking for a developer."}
        negative_min_quals = [
            "Senior developer with 5+ years of experience.",
            "Expert developer with 10 years of experience.",
            "Lead developer with 7 years of experience.",
            "Applicants will have 5+ years experience in industry as a Software Engineer",
            "7+ years of hands-on experience as a Server Engineer with Java",
            "2-3 years of experience software development - contributed to code, code reviews, design reviews, and maintain production systems.",
        ]
        pref_qual = "Experience with Python."
        for min_qual in negative_min_quals:
            self.assertFalse(is_entry_level(job, min_qual, pref_qual))

    def test_positive_phrases_in_pref_qual(self):
        job = {"postingTitle": "Software Engineer", "jobSummary": "Looking for a developer."}
        min_qual = "Bachelor's degree in Computer Science."
        positive_pref_quals = [
            "Entry-level experience preferred.",
            "New graduates are welcome.",
            "Junior developers are encouraged to apply.",
            "We prefer you to be a new grad, graduating in..."
            "0-1+ years expected with previous internship experience"
        ]
        for pref_qual in positive_pref_quals:
            self.assertTrue(is_entry_level(job, min_qual, pref_qual))

    def test_negative_keywords_in_pref_qual(self):
        job = {"postingTitle": "Software Engineer", "jobSummary": "Looking for a developer."}
        min_qual = "Bachelor's degree in Computer Science."
        negative_pref_quals = [
            "Senior-level experience preferred.",
            "Expert developers are encouraged to apply.",
            "10+ years of experience required.",
            "2-3+ years expected with previous internship experience"
            "3+ years of industry experience, BS in Computer Engineering, Electrical Engineering, Computer Science, Math, or equivalent experience.",

        ]
        for pref_qual in negative_pref_quals:
            self.assertFalse(is_entry_level(job, min_qual, pref_qual))

    def test_zero_start_range_in_min_qual(self):
        job = {"postingTitle": "Software Engineer", "jobSummary": "Looking for a developer."}
        min_qual = "0-2 years of experience."
        pref_qual = "Experience with Python."
        self.assertTrue(is_entry_level(job, min_qual, pref_qual))

    def test_min_years_exceeds_threshold(self):
        job = {"postingTitle": "Software Engineer", "jobSummary": "Looking for a developer."}
        min_qual = "3+ years of experience."
        pref_qual = "Experience with Python."
        self.assertFalse(is_entry_level(job, min_qual, pref_qual))

    def test_min_years_within_threshold(self):
        job = {"postingTitle": "Software Engineer", "jobSummary": "Looking for a developer."}
        min_qual = "1 year of experience."
        pref_qual = "Experience with Python."
        self.assertTrue(is_entry_level(job, min_qual, pref_qual))

    def test_no_specific_years_or_keywords(self):
        job = {"postingTitle": "Software Engineer", "jobSummary": "Looking for a developer."}
        min_qual = "Bachelor's degree in Computer Science."
        pref_qual = "Experience with Python."
        self.assertTrue(is_entry_level(job, min_qual, pref_qual))

    def test_empty_inputs(self):
        job = {"postingTitle": "", "jobSummary": ""}
        min_qual = ""
        pref_qual = ""
        self.assertTrue(is_entry_level(job, min_qual, pref_qual))

if __name__ == '__main__':
    unittest.main()