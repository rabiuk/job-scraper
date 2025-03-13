import unittest
from utils import is_entry_level
from setup_environment import setup_environment

setup_environment()

class TestIsEntryLevel(unittest.TestCase):

    def test_positive_keywords_in_title(self):
        job = {
            "job_title": "Junior Software Engineer",
            "job_description": "Looking for a junior developer.",
            "minimum_qualifications": "Bachelor's degree in Computer Science.",
            "preferred_qualifications": "Experience with Python."
        }
        self.assertTrue(is_entry_level(job))

    def test_negative_keywords_in_title(self):
        job = {
            "job_title": "Senior Software Engineer",
            "job_description": "Looking for a senior developer.",
            "minimum_qualifications": "Bachelor's degree in Computer Science.",
            "preferred_qualifications": "Experience with Python."
        }
        self.assertFalse(is_entry_level(job))

    def test_positive_phrases_in_description(self):
        job = {
            "job_title": "Software Engineer",
            "job_description": "This is an entry-level position.",
            "minimum_qualifications": "Bachelor's degree in Computer Science.",
            "preferred_qualifications": "Experience with Python."
        }
        self.assertTrue(is_entry_level(job))

    def test_negative_keywords_in_description(self):
        jobs = [
            {"job_title": "Software Engineer", "job_description": "This is a senior position."},
            {"job_title": "Software Engineer", "job_description": "This is a lead software engineer position."},
        ]
        for job in jobs:
            job.setdefault("minimum_qualifications", "Bachelor's degree in Computer Science.")
            job.setdefault("preferred_qualifications", "Experience with Python.")
            self.assertFalse(is_entry_level(job))

    def test_positive_keywords_in_min_qual(self):
        job = {
            "job_title": "Software Engineer",
            "job_description": "Looking for a developer."
        }
        positive_min_quals = [
            "Junior developer with 0-1 years of experience.",
            "Entry-level developer with 1 year of experience.",
            "New grad with 0 years of experience.",
            "Bachelors of Science in Computer Science with 0-3+ years of relevant confirmed experience",
            "Bachelors of Science in Computer Science with 1-3+ years of relevant confirmed experience",
        ]
        for min_qual in positive_min_quals:
            job["minimum_qualifications"] = min_qual
            job["preferred_qualifications"] = "Experience with Python."
            self.assertTrue(is_entry_level(job))

    def test_negative_keywords_in_min_qual(self):
        job = {
            "job_title": "Software Engineer",
            "job_description": "Looking for a developer."
        }
        negative_min_quals = [
            "Senior developer with 5+ years of experience.",
            "Expert developer with 10 years of experience.",
            "Lead developer with 7 years of experience.",
            "Applicants will have 5+ years experience in industry as a Software Engineer",
            "7+ years of hands-on experience as a Server Engineer with Java",
            "2-3 years of experience software development - contributed to code, code reviews, design reviews, and maintain production systems.",
        ]
        for min_qual in negative_min_quals:
            job["minimum_qualifications"] = min_qual
            job["preferred_qualifications"] = "Experience with Python."
            self.assertFalse(is_entry_level(job))

    def test_positive_phrases_in_pref_qual(self):
        job = {
            "job_title": "Software Engineer",
            "job_description": "Looking for a developer.",
            "minimum_qualifications": "Bachelor's degree in Computer Science."
        }
        positive_pref_quals = [
            "Entry-level experience preferred.",
            "New graduates are welcome.",
            "Junior developers are encouraged to apply.",
            "We prefer you to be a new grad, graduating in...",
            "0-1+ years expected with previous internship experience"
        ]
        for pref_qual in positive_pref_quals:
            job["preferred_qualifications"] = pref_qual
            self.assertTrue(is_entry_level(job))

    def test_negative_keywords_in_pref_qual(self):
        job = {
            "job_title": "Software Engineer",
            "job_description": "Looking for a developer.",
            "minimum_qualifications": "Bachelor's degree in Computer Science."
        }
        negative_pref_quals = [
            "Senior-level experience preferred.",
            "Expert developers are encouraged to apply.",
            "10+ years of experience required.",
            "2-3+ years expected with previous internship experience",
            "3+ years of industry experience, BS in Computer Engineering, Electrical Engineering, Computer Science, Math, or equivalent experience.",
        ]
        for pref_qual in negative_pref_quals:
            job["preferred_qualifications"] = pref_qual
            self.assertFalse(is_entry_level(job))

    def test_zero_start_range_in_min_qual(self):
        job = {
            "job_title": "Software Engineer",
            "job_description": "Looking for a developer.",
            "minimum_qualifications": "0-2 years of experience.",
            "preferred_qualifications": "Experience with Python."
        }
        self.assertTrue(is_entry_level(job))

    def test_min_years_exceeds_threshold(self):
        job = {
            "job_title": "Software Engineer",
            "job_description": "Looking for a developer.",
            "minimum_qualifications": "3+ years of experience.",
            "preferred_qualifications": "Experience with Python."
        }
        self.assertFalse(is_entry_level(job))

    def test_min_years_within_threshold(self):
        job = {
            "job_title": "Software Engineer",
            "job_description": "Looking for a developer.",
            "minimum_qualifications": "1 year of experience.",
            "preferred_qualifications": "Experience with Python."
        }
        self.assertTrue(is_entry_level(job))

    def test_no_specific_years_or_keywords(self):
        job = {
            "job_title": "Software Engineer",
            "job_description": "Looking for a developer.",
            "minimum_qualifications": "Bachelor's degree in Computer Science.",
            "preferred_qualifications": "Experience with Python."
        }
        self.assertTrue(is_entry_level(job))

    def test_empty_inputs(self):
        job = {
            "job_title": "",
            "job_description": "",
            "minimum_qualifications": "",
            "preferred_qualifications": ""
        }
        self.assertTrue(is_entry_level(job))

    def test_bing_metrics_job(self):
        # Test the specific job that was filtered out
        job = {
            "job_title": "Software Engineer",
            "job_description": (
                "do you want to make a real impact on how billions of people experience search every day? "
                "here’s your chance! the bing metrics team is on the lookout for passionate and talented "
                "full-stack developers and data scientists who are excited to build cutting-edge solutions "
                "for measuring and enhancing the quality of search results at bing. in this role, you’ll be "
                "part of a dynamic, international team responsible for ensuring bing delivers the best, most "
                "accurate, and reliable results to users worldwide. you’ll dive deep into petabytes of user data, "
                "uncovering potential issues, and utilizing advanced ai techniques, including llms, to evaluate "
                "and improve search quality across the board. whether it’s at the query level, on-page insights, "
                "or evaluating entire search results, you’ll use the latest tech to make bing smarter, faster, "
                "and better for users everywhere."
            ),
            "minimum_qualifications": "",
            "preferred_qualifications": ""
        }
        self.assertTrue(is_entry_level(job))

if __name__ == '__main__':
    unittest.main()