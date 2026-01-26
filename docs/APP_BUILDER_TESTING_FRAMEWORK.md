# App Builder Testing Framework

**Author**: A.R.C.H.I.E. Platform
**Date**: 2026-01-07
**Phase**: Week 5 - Testing Framework
**Status**: ✅ Complete

---

## Overview

The App Builder Testing Framework provides comprehensive automated testing capabilities for generated applications. It includes two specialized agents that work together to generate and execute test suites for both backend (Flask/pytest) and frontend (React/Jest) code.

---

## Architecture

### Components

```
Testing Framework
├── Test Generator Agent (test_generator.py)
│   ├── Backend Test Generation (pytest)
│   │   ├── Configuration Files (pytest.ini, conftest.py)
│   │   ├── Model Tests (SQLAlchemy models)
│   │   ├── API Tests (CRUD endpoints)
│   │   ├── Authentication Tests (JWT auth)
│   │   └── Integration Tests (workflows)
│   └── Frontend Test Generation (Jest/React Testing Library)
│       ├── Configuration Files (jest.config.js, setupTests.js)
│       ├── Component Tests (List, Form, Detail)
│       ├── Service Tests (API services)
│       └── Integration Tests (user workflows)
│
└── Test Runner Agent (test_runner.py)
    ├── Backend Test Execution (pytest)
    │   ├── XML Result Parsing (JUnit format)
    │   ├── Coverage Analysis (pytest-cov)
    │   └── Failure Reporting
    └── Frontend Test Execution (Jest/npm test)
        ├── JSON Result Parsing
        ├── Coverage Analysis (Istanbul)
        └── Failure Reporting
```

---

## Test Generator Agent

### Purpose
Automatically generates comprehensive test suites based on the technical plan, including unit tests, integration tests, and configuration files.

### Capabilities

#### Backend Test Generation (pytest)
Generates **8+ test files per project**:

1. **pytest.ini** - Test configuration with markers and coverage settings
2. **conftest.py** - Pytest fixtures (app, client, db_session, auth_headers)
3. **requirements-test.txt** - Testing dependencies
4. **Model Tests** (test_models/test_*.py) - One file per database model
   - Create/Read/Update/Delete operations
   - Serialization (to_dict)
   - Relationship validation
5. **API Tests** (test_api/test_*.py) - One file per resource
   - GET /resource - List all
   - POST /resource - Create new
   - GET /resource/<id> - Get single
   - PUT /resource/<id> - Update
   - DELETE /resource/<id> - Delete
   - Pagination testing
   - Unauthorized access testing
6. **Authentication Tests** (test_api/test_auth.py)
   - Signup (success, duplicate email, invalid email, weak password)
   - Login (success, invalid credentials)
   - Token refresh
   - Logout
   - Protected endpoint access
7. **Integration Tests** (test_integration/test_workflows.py)
   - Complete CRUD workflow
   - Authentication workflow
   - Pagination workflow
   - Error handling

#### Frontend Test Generation (Jest/React Testing Library)
Generates **9+ test files per project**:

1. **jest.config.js** - Jest configuration with coverage thresholds
2. **setupTests.js** - Test setup with mocks (localStorage, matchMedia)
3. **test-utils.js** - Custom render functions and helpers
4. **Component Tests** - One file per CRUD component
   - List component (loading, display, error, delete)
   - Form component (render, submit, validation, errors)
   - Detail component (loading, display, navigation)
5. **Authentication Tests**
   - Login component (render, submit, error, validation)
   - Signup component (render, submit, error, validation)
6. **Service Tests** - One file per API service
   - GET all items
   - GET by ID
   - POST create
   - PUT update
   - DELETE remove
7. **Integration Tests**
   - App rendering and navigation
   - Complete authentication flow

### Usage

```python
from agents.test_generator import TestGenerator

# Initialize generator
generator = TestGenerator(
    project_id=1,
    project_plan=plan_dict,
    architecture_plan=arch_dict  # optional
)

# Generate tests
result = await generator.generate_tests(
    test_backend=True,
    test_frontend=True
)

# Result structure
{
    'success': True,
    'test_files': 17,  # Total files generated
    'backend_tests': 8,
    'frontend_tests': 9,
    'file_count': 17,
    'frameworks': {
        'backend': 'pytest',
        'frontend': 'jest'
    }
}
```

### Generated File Structure

```
project_root/
├── backend/
│   ├── pytest.ini
│   ├── requirements-test.txt
│   └── tests/
│       ├── conftest.py
│       ├── test_models/
│       │   ├── test_users.py
│       │   ├── test_todos.py
│       │   └── test_<model>.py
│       ├── test_api/
│       │   ├── test_auth.py
│       │   ├── test_users.py
│       │   ├── test_todos.py
│       │   └── test_<resource>.py
│       └── test_integration/
│           └── test_workflows.py
│
└── frontend/
    ├── jest.config.js
    └── src/
        ├── setupTests.js
        ├── test-utils.js
        ├── components/
        │   ├── Auth/
        │   │   ├── Login.test.js
        │   │   └── Signup.test.js
        │   └── <Resource>/
        │       ├── <Resource>List.test.js
        │       └── <Resource>Form.test.js
        ├── services/
        │   ├── authService.test.js
        │   └── <resource>Service.test.js
        └── __tests__/
            └── integration.test.js
```

---

## Test Runner Agent

### Purpose
Executes generated test suites, parses results, generates coverage reports, and provides detailed failure information.

### Capabilities

#### Backend Test Execution (pytest)
- Runs pytest with coverage analysis
- Parses JUnit XML output for test results
- Parses coverage.json for code coverage
- Extracts detailed failure information
- Supports test markers (unit, integration, api, auth)

#### Frontend Test Execution (Jest)
- Runs Jest via npm test
- Parses JSON output for test results
- Parses coverage-summary.json for coverage
- Extracts failure details
- Supports CI mode (non-interactive)

#### Report Generation
Generates reports in multiple formats:
- **Text** - Console-friendly summary
- **JSON** - Machine-readable format
- **HTML** - Web-based report (basic)

### Usage

```python
from agents.test_runner import TestRunner

# Initialize runner
runner = TestRunner(
    project_id=1,
    project_path='/path/to/project',
    project_plan=plan_dict  # optional
)

# Run tests
results = await runner.run_tests(
    test_backend=True,
    test_frontend=True,
    test_type='all'  # 'all', 'unit', 'integration'
)

# Generate report
report = runner.generate_report(format='text')
print(report)
```

### Result Structure

```python
{
    'timestamp': '2026-01-07T12:00:00',
    'overall_success': True,  # All tests passed
    'total_tests': 25,
    'passed_tests': 24,
    'failed_tests': 1,
    'skipped_tests': 0,
    'success_rate': 96.0,

    'backend': {
        'success': True,
        'framework': 'pytest',
        'total': 12,
        'passed': 12,
        'failed': 0,
        'skipped': 0,
        'duration': 5.23,
        'failures': [],
        'coverage': {
            'total_statements': 250,
            'covered_statements': 220,
            'coverage_percent': 88.0,
            'files': { ... }
        },
        'output': '...',
        'error': None
    },

    'frontend': {
        'success': True,
        'framework': 'jest',
        'total': 13,
        'passed': 12,
        'failed': 1,
        'skipped': 0,
        'duration': 3.45,
        'failures': [
            {
                'test_name': 'renders list correctly',
                'file': 'TodoList.test.js',
                'message': 'Expected element to be in document',
                'details': '...'
            }
        ],
        'coverage': {
            'statements': 82.5,
            'branches': 75.0,
            'functions': 80.0,
            'lines': 82.5,
            'files': { ... }
        },
        'output': '...',
        'error': None
    },

    'coverage': {
        'backend': { ... },
        'frontend': { ... }
    }
}
```

### Text Report Example

```
================================================================================
TEST RESULTS REPORT
================================================================================
Timestamp: 2026-01-07T12:00:00
Overall Success: ✅ PASS

SUMMARY
--------------------------------------------------------------------------------
Total Tests:   25
Passed:        24 ✅
Failed:        1 ❌
Skipped:       0 ⏭️
Success Rate:  96.00%

BACKEND TESTS (pytest)
--------------------------------------------------------------------------------
Status:   ✅ PASS
Total:    12
Passed:   12
Failed:   0
Skipped:  0
Duration: 5.23s
Coverage: 88.0%

FRONTEND TESTS (Jest)
--------------------------------------------------------------------------------
Status:   ❌ FAIL
Total:    13
Passed:   12
Failed:   1
Skipped:  0
Duration: 3.45s
Coverage:
  Statements: 82.5%
  Branches:   75.0%
  Functions:  80.0%
  Lines:      82.5%

Failed Tests:
  - renders list correctly
    File: TodoList.test.js
    Message: Expected element to be in document

================================================================================
```

---

## API Endpoints

### 1. Generate Tests

**Endpoint**: `POST /api/projects/<project_id>/generate-tests`

**Authentication**: Required (login_required)

**Permission**: APP_BUILDER_CREATE

**Request Body**:
```json
{
    "backend": true,    // Generate backend tests
    "frontend": true    // Generate frontend tests
}
```

**Response**:
```json
{
    "success": true,
    "test_files": 17,
    "backend_tests": 8,
    "frontend_tests": 9,
    "frameworks": {
        "backend": "pytest",
        "frontend": "jest"
    },
    "message": "Tests generated successfully! 17 test files created."
}
```

**Prerequisites**:
- Project status must be 'generated' or 'tested'
- Code must be generated before creating tests

---

### 2. Run Tests

**Endpoint**: `POST /api/projects/<project_id>/run-tests`

**Authentication**: Required (login_required)

**Permission**: APP_BUILDER_CREATE

**Request Body**:
```json
{
    "backend": true,       // Run backend tests
    "frontend": true,      // Run frontend tests
    "test_type": "all"    // "all", "unit", "integration", "api", "auth"
}
```

**Response**:
```json
{
    "success": true,
    "test_results": {
        "overall_success": true,
        "total_tests": 25,
        "passed_tests": 24,
        "failed_tests": 1,
        "success_rate": 96.0,
        "backend": { ... },
        "frontend": { ... }
    },
    "report": "...",  // Text report
    "message": "Tests executed successfully"
}
```

**Side Effects**:
- Updates project status to 'tested' or 'test_failed'
- Saves test results to database
- Records audit log

---

### 3. Get Test Results

**Endpoint**: `GET /api/projects/<project_id>/test-results`

**Authentication**: Required (login_required)

**Permission**: APP_BUILDER_CREATE

**Response**:
```json
{
    "success": true,
    "test_results": { ... },  // Latest test results
    "last_test_run": "2026-01-07T12:00:00"
}
```

---

## Test Coverage

### Backend Coverage Thresholds
Set in `pytest.ini`:
```ini
[coverage:report]
fail_under = 70
```

### Frontend Coverage Thresholds
Set in `jest.config.js`:
```javascript
coverageThreshold: {
  global: {
    branches: 70,
    functions: 70,
    lines: 70,
    statements: 70
  }
}
```

---

## Dependencies

### Backend Testing Dependencies
```
pytest==7.4.3
pytest-cov==4.1.0
pytest-flask==1.3.0
pytest-mock==3.12.0
faker==20.1.0
factory-boy==3.3.0
coverage==7.3.2
```

### Frontend Testing Dependencies
```json
{
  "@testing-library/react": "^13.4.0",
  "@testing-library/jest-dom": "^5.16.5",
  "@testing-library/user-event": "^14.4.3",
  "jest": "^27.5.1"
}
```

---

## Best Practices

### Test Organization
1. **Separate by type**: Unit, integration, and e2e tests in different directories
2. **One test file per source file**: Easy to locate and maintain
3. **Descriptive test names**: Clearly state what is being tested
4. **Arrange-Act-Assert**: Structure tests consistently

### Test Quality
1. **Test one thing**: Each test should verify a single behavior
2. **Independent tests**: Tests should not depend on each other
3. **Clean up**: Use fixtures and teardown methods
4. **Mock external dependencies**: Database, APIs, file system

### Coverage Goals
1. **Aim for 70%+**: Good balance of coverage vs. effort
2. **100% critical paths**: Authentication, payments, data mutations
3. **Don't chase 100%**: Diminishing returns after 85%

---

## Workflow Integration

### Complete Development Workflow

```
1. User describes application
   ↓
2. Clarification Agent asks questions
   ↓
3. Planner Agent generates technical plan
   ↓
4. User approves plan
   ↓
5. Backend Generator creates Flask code (14 files)
   ↓
6. Frontend Generator creates React code (27 files)
   ↓
7. Database Generator creates SQL schema (7 files)
   ↓
8. Test Generator creates test suites (17 files) ← NEW
   ↓
9. Test Runner executes tests ← NEW
   ↓
10. Deployment (Week 6 - Coming Soon)
```

---

## Database Schema Updates

### New Columns in `app_builder_projects`

```sql
ALTER TABLE app_builder_projects
ADD COLUMN IF NOT EXISTS tests_generated_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS test_results JSONB,
ADD COLUMN IF NOT EXISTS last_test_run TIMESTAMP;
```

### Project Status Values
- `draft` - Initial state
- `clarifying` - Gathering requirements
- `planning` - Generating technical plan
- `planned` - Plan ready for approval
- `generating` - Generating code
- `generated` - Code generated
- `tested` - Tests passed ← NEW
- `test_failed` - Tests failed ← NEW
- `deployed` - Deployed to production (Week 6)

---

## Error Handling

### Common Errors

#### 1. pytest Not Found
**Error**: `pytest not found. Make sure it is installed`

**Solution**:
```bash
cd backend
pip install -r requirements-test.txt
```

#### 2. npm Not Found
**Error**: `npm not found. Make sure Node.js and npm are installed`

**Solution**: Install Node.js from https://nodejs.org/

#### 3. node_modules Not Found
**Error**: `node_modules not found. Run "npm install" first.`

**Solution**:
```bash
cd frontend
npm install
```

#### 4. Code Not Generated
**Error**: `Code must be generated before creating tests`

**Solution**: Run code generation first via `/api/projects/<id>/generate`

---

## Performance Considerations

### Test Generation
- **Time**: ~1-2 seconds for 17 files
- **Memory**: Minimal (< 50 MB)
- **Async**: Fully asynchronous using asyncio

### Test Execution
- **Backend**: 5-10 seconds for typical suite
- **Frontend**: 3-8 seconds for typical suite
- **Total**: 8-18 seconds for full suite
- **Parallel**: Can run backend and frontend simultaneously

---

## Future Enhancements

### Planned for Week 6 (Deployment)
1. **Performance Tests** - Load testing with Locust
2. **E2E Tests** - Browser automation with Selenium/Playwright
3. **Security Tests** - OWASP scanning
4. **CI/CD Integration** - GitHub Actions, GitLab CI
5. **Test Reporting Dashboard** - Visual test result trends

### Planned for Future Releases
1. **Mutation Testing** - Code quality measurement
2. **Visual Regression Testing** - UI screenshot comparison
3. **API Contract Testing** - OpenAPI/Swagger validation
4. **Accessibility Testing** - WCAG compliance
5. **Test Data Generation** - Faker integration for realistic data

---

## Files Modified

### New Files Created
1. `/mnt/archie_brain/platform_v2/tools/app_builder/agents/test_generator.py` (900+ lines)
2. `/mnt/archie_brain/platform_v2/tools/app_builder/agents/test_runner.py` (700+ lines)

### Modified Files
1. `/mnt/archie_brain/platform_v2/tools/app_builder/routes.py`
   - Added `/api/projects/<id>/generate-tests` endpoint
   - Added `/api/projects/<id>/run-tests` endpoint
   - Added `/api/projects/<id>/test-results` endpoint

---

## Testing the Testing Framework

### Manual Test

```bash
# Test the generator
cd /mnt/archie_brain/platform_v2/tools/app_builder/agents
python3 test_generator.py

# Expected output:
✅ Test Generation Complete!
Total test files: 17
Backend tests: 8
Frontend tests: 9

Frameworks:
  Backend: pytest
  Frontend: jest
```

### API Test

```bash
# 1. Generate tests
curl -X POST http://localhost:3000/api/projects/1/generate-tests \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"backend": true, "frontend": true}'

# 2. Run tests
curl -X POST http://localhost:3000/api/projects/1/run-tests \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"backend": true, "frontend": true, "test_type": "all"}'

# 3. Get results
curl -X GET http://localhost:3000/api/projects/1/test-results \
  -H "Authorization: Bearer YOUR_TOKEN"
```

---

## Conclusion

The App Builder Testing Framework provides comprehensive, automated testing capabilities that ensure generated applications are production-ready. With support for both backend and frontend testing, coverage analysis, and detailed reporting, it significantly reduces the time and effort required to validate generated code.

**Key Achievements**:
- ✅ Automated test generation (17 files per project)
- ✅ Comprehensive test coverage (models, APIs, components, services)
- ✅ Automated test execution (pytest + Jest)
- ✅ Coverage analysis (backend 70%+, frontend 70%+)
- ✅ Detailed failure reporting
- ✅ Multiple report formats (text, JSON, HTML)
- ✅ Full API integration

**Next Phase**: Week 6 - Deployment & CI/CD Integration

---

**Document Version**: 1.0
**Last Updated**: 2026-01-07
**Maintained by**: A.R.C.H.I.E. Platform Development Team
