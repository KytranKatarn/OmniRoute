-- ============================================================
-- LLM Ecosystem Redesign — Human Staff Name Cleanup
-- Rule: AI = ACRONYM with dots. Human = First Last (no code names).
-- Decision #441
-- ============================================================

BEGIN;

UPDATE agents SET display_name = 'Marcus Rivera', first_name = 'Marcus', last_name = 'Rivera', title = 'Chief Architect' WHERE id = 5 AND name = 'Architect';
UPDATE agents SET display_name = 'Amira Hassan', first_name = 'Amira', last_name = 'Hassan', title = 'Infrastructure Engineer' WHERE name = 'Circuit' AND department = 'Operations & Infrastructure';
UPDATE agents SET display_name = 'Carmen Reyes', first_name = 'Carmen', last_name = 'Reyes', title = 'Logistics Coordinator' WHERE name = 'Dispatch' AND department = 'Logistics & Supply Chain';
UPDATE agents SET display_name = 'Yuki Nakamura', first_name = 'Yuki', last_name = 'Nakamura', title = 'Financial Analyst' WHERE name = 'Value' AND department = 'Finance & Accounting';
UPDATE agents SET display_name = 'Aria Chen', first_name = 'Aria', last_name = 'Chen', title = 'Lead Software Engineer' WHERE name = 'CodeSmith' AND department = 'Engineering & Technology';
UPDATE agents SET display_name = 'Rowan McAllister', first_name = 'Rowan', last_name = 'McAllister', title = 'Penetration Tester & Red Team Lead' WHERE name = 'Thorn' AND department = 'Security & Compliance';
UPDATE agents SET display_name = 'Olumide Adeyemi', first_name = 'Olumide', last_name = 'Adeyemi', title = 'Senior Data Scientist' WHERE name = 'Cortex' AND department = 'Research & Development';
UPDATE agents SET display_name = 'Isabella Fernandez', first_name = 'Isabella', last_name = 'Fernandez', title = 'Creative Director' WHERE name = 'Nova' AND department = 'Creative & Design';
UPDATE agents SET display_name = 'Lea Dubois', first_name = 'Lea', last_name = 'Dubois', title = 'Senior Copywriter' WHERE name = 'Scribe' AND department = 'Marketing & Communications';
UPDATE agents SET display_name = 'Sofia Petrov', first_name = 'Sofia', last_name = 'Petrov', title = 'Head of Research & Knowledge' WHERE name = 'Scholar' AND department = 'Documentation & Knowledge';
UPDATE agents SET display_name = 'Kwame Asante', first_name = 'Kwame', last_name = 'Asante', title = 'Client Success Manager' WHERE name = 'Envoy' AND department = 'Customer Success & Support';
UPDATE agents SET display_name = 'Haruto Takahashi', first_name = 'Haruto', last_name = 'Takahashi', title = 'People & Culture Lead' WHERE name = 'Sage' AND department = 'Human Resources & Culture';
UPDATE agents SET display_name = 'Dr. Priya Sharma', first_name = 'Priya', last_name = 'Sharma', title = 'Medical Director' WHERE name = 'Zenith' AND department = 'Medical & Wellness';
UPDATE agents SET display_name = 'Dr. Kenji Yamamoto', first_name = 'Kenji', last_name = 'Yamamoto', title = 'Legal Counsel' WHERE name = 'Crucible' AND department = 'Legal & Regulatory';
UPDATE agents SET display_name = 'Fatima Al-Rashid', first_name = 'Fatima', last_name = 'Al-Rashid', title = 'Senior Diplomatic Advisor' WHERE name = 'Luna' AND department = 'Diplomatic & External Relations';
UPDATE agents SET display_name = 'Jin Park', first_name = 'Jin', last_name = 'Park', title = 'Data & Vision Specialist' WHERE name = 'Nexus' AND department = 'Analytics & Intelligence';

COMMIT;
