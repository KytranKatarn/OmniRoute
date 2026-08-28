"""
Frontend Generator Agent - Phase 2: App Builder
Generates production-ready frontend code (React/Vue) from technical plans

Purpose:
- Generate React/Vue components
- Generate routing and navigation
- Generate state management (Redux/Context/Pinia)
- Generate API service layer
- Generate authentication components
- Generate CRUD components
- Generate styling (CSS/Tailwind)
- Generate configuration files

Author: A.R.C.H.I.E. Platform
Date: 2026-01-07
"""

import json
from typing import Dict, List, Any
from datetime import datetime

# Try to import database for file storage
DB_AVAILABLE = False
try:
    import sys

    sys.path.append("/mnt/archie_brain/platform_v2")
    from tools.database import db

    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False


class FrontendGenerator:
    """
    Frontend Generator Agent - Generates frontend code from plans

    Supports:
    - React (JavaScript/JSX)
    - Vue (future)

    Generates:
    - Component files (functional components)
    - Routing (React Router)
    - State management (Redux Toolkit/Context API)
    - API service layer (axios)
    - Authentication components
    - CRUD components
    - Configuration files
    """

    def __init__(self, project_id: int, plan: Dict[str, Any], architecture: Dict[str, Any]):
        """
        Initialize Frontend Generator

        Args:
            project_id: Project ID from app_builder_projects
            plan: Technical plan from PlannerAgent
            architecture: Architecture details from ArchitectAgent
        """
        self.project_id = project_id
        self.plan = plan
        self.architecture = architecture
        self.generated_files = []

    async def generate_frontend(self) -> Dict[str, Any]:
        """
        Main method to generate frontend code

        Returns:
            Dict containing all generated files and metadata
        """
        print(f"\n[Frontend Generator] Generating frontend for project {self.project_id}...")

        tech_stack = self.plan.get("tech_stack", {})
        frontend_framework = tech_stack.get("frontend", "React")

        # Determine which generator to use
        if "React" in frontend_framework:
            result = await self._generate_react_frontend()
        elif "Vue" in frontend_framework:
            result = await self._generate_vue_frontend()
        else:
            raise ValueError(f"Unsupported frontend framework: {frontend_framework}")

        print(f"[Frontend Generator] ✅ Generated {len(result['files'])} frontend files\n")
        return result

    # ========================================================================
    # REACT FRONTEND GENERATION
    # ========================================================================

    async def _generate_react_frontend(self) -> Dict[str, Any]:
        """Generate complete React frontend"""
        print("[Frontend Generator] Generating React frontend...")

        files = {}

        # 1. Generate package.json
        files["frontend/package.json"] = self._generate_react_package_json()
        print("  ✓ Generated package.json")

        # 2. Generate public/index.html
        files["frontend/public/index.html"] = self._generate_index_html()
        print("  ✓ Generated index.html")

        # 3. Generate src/index.js
        files["frontend/src/index.js"] = self._generate_react_index()
        print("  ✓ Generated index.js")

        # 4. Generate src/App.js
        files["frontend/src/App.js"] = self._generate_react_app()
        print("  ✓ Generated App.js")

        # 5. Generate API service layer
        api_files = self._generate_api_services()
        files.update(api_files)
        print(f"  ✓ Generated {len(api_files)} API service files")

        # 6. Generate authentication components
        if self._has_authentication():
            auth_files = self._generate_auth_components()
            files.update(auth_files)
            print(f"  ✓ Generated authentication components")

        # 7. Generate CRUD components
        crud_files = self._generate_crud_components()
        files.update(crud_files)
        print(f"  ✓ Generated {len(crud_files)} CRUD component files")

        # 8. Generate layout components
        layout_files = self._generate_layout_components()
        files.update(layout_files)
        print(f"  ✓ Generated layout components")

        # 9. Generate state management
        state_files = self._generate_state_management()
        files.update(state_files)
        print(f"  ✓ Generated state management files")

        # 10. Generate routing
        files["frontend/src/routes/AppRoutes.jsx"] = self._generate_react_routing()
        print("  ✓ Generated routing")

        # 11. Generate styles
        style_files = self._generate_styles()
        files.update(style_files)
        print(f"  ✓ Generated style files")

        # 12. Generate .env.example
        files["frontend/.env.example"] = self._generate_frontend_env()
        print("  ✓ Generated .env.example")

        # 13. Generate README
        files["frontend/README.md"] = self._generate_frontend_readme("React")
        print("  ✓ Generated README.md")

        # 14. Generate .gitignore
        files["frontend/.gitignore"] = self._generate_gitignore()
        print("  ✓ Generated .gitignore")

        # Store files for database persistence
        self.generated_files = [
            {
                "file_path": path,
                "content": content,
                "file_type": self._get_file_type(path),
            }
            for path, content in files.items()
        ]

        return {
            "framework": "React",
            "files": self.generated_files,
            "file_count": len(files),
            "structure": self._get_file_structure(files),
            "generated_at": datetime.now().isoformat(),
        }

    def _generate_react_package_json(self) -> str:
        """Generate package.json for React"""
        project_name = self.plan.get("name", "app").lower().replace(" ", "-")
        state_mgmt = self.architecture.get("state_management", {}).get("pattern", {})
        uses_redux = "Redux" in state_mgmt.get("name", "")

        dependencies = {
            "react": "^18.2.0",
            "react-dom": "^18.2.0",
            "react-router-dom": "^6.20.0",
            "axios": "^1.6.2",
        }

        if uses_redux:
            dependencies.update({"@reduxjs/toolkit": "^2.0.1", "react-redux": "^9.0.4"})

        dev_dependencies = {
            "@testing-library/react": "^14.1.2",
            "@testing-library/jest-dom": "^6.1.5",
            "react-scripts": "5.0.1",
        }

        return json.dumps(
            {
                "name": project_name,
                "version": "0.1.0",
                "private": True,
                "dependencies": dependencies,
                "devDependencies": dev_dependencies,
                "scripts": {
                    "start": "react-scripts start",
                    "build": "react-scripts build",
                    "test": "react-scripts test",
                    "eject": "react-scripts eject",
                },
                "eslintConfig": {"extends": ["react-app"]},
                "browserslist": {
                    "production": [">0.2%", "not dead", "not op_mini all"],
                    "development": [
                        "last 1 chrome version",
                        "last 1 firefox version",
                        "last 1 safari version",
                    ],
                },
            },
            indent=2,
        )

    def _generate_index_html(self) -> str:
        """Generate public/index.html"""
        project_name = self.plan.get("name", "App")

        return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="theme-color" content="#000000" />
    <meta name="description" content="{project_name} - Built with A.R.C.H.I.E." />
    <title>{project_name}</title>
  </head>
  <body>
    <noscript>You need to enable JavaScript to run this app.</noscript>
    <div id="root"></div>
  </body>
</html>
"""

    def _generate_react_index(self) -> str:
        """Generate src/index.js"""
        state_mgmt = self.architecture.get("state_management", {}).get("pattern", {})
        uses_redux = "Redux" in state_mgmt.get("name", "")

        if uses_redux:
            return """import React from 'react';
import ReactDOM from 'react-dom/client';
import { Provider } from 'react-redux';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import store from './store/store';
import './index.css';

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <Provider store={store}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </Provider>
  </React.StrictMode>
);
"""
        else:
            return """import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import './index.css';

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);
"""

    def _generate_react_app(self) -> str:
        """Generate src/App.js"""
        has_auth = self._has_authentication()

        if has_auth:
            return """import React, { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import AppRoutes from './routes/AppRoutes';
import Layout from './components/Layout/Layout';
import { checkAuth } from './services/authService';
import './App.css';

function App() {
  const navigate = useNavigate();

  useEffect(() => {
    // Check if user is authenticated on mount
    const token = localStorage.getItem('access_token');
    if (token) {
      checkAuth().catch(() => {
        localStorage.removeItem('access_token');
        navigate('/login');
      });
    }
  }, [navigate]);

  return (
    <div className="App">
      <Layout>
        <AppRoutes />
      </Layout>
    </div>
  );
}

export default App;
"""
        else:
            return """import React from 'react';
import AppRoutes from './routes/AppRoutes';
import Layout from './components/Layout/Layout';
import './App.css';

function App() {
  return (
    <div className="App">
      <Layout>
        <AppRoutes />
      </Layout>
    </div>
  );
}

export default App;
"""

    def _generate_api_services(self) -> Dict[str, str]:
        """Generate API service layer with axios"""
        files = {}

        # Base API service
        files[
            "frontend/src/services/api.js"
        ] = """import axios from 'axios';

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:5000';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor to add auth token
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Response interceptor to handle errors
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;

    // If 401 and not already retried, try to refresh token
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true;

      try {
        const refreshToken = localStorage.getItem('refresh_token');
        if (refreshToken) {
          const response = await axios.post(`${API_BASE_URL}/api/auth/refresh`, {
            refresh_token: refreshToken,
          });

          const { access_token } = response.data;
          localStorage.setItem('access_token', access_token);

          originalRequest.headers.Authorization = `Bearer ${access_token}`;
          return api(originalRequest);
        }
      } catch (refreshError) {
        // Refresh failed, redirect to login
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        window.location.href = '/login';
        return Promise.reject(refreshError);
      }
    }

    return Promise.reject(error);
  }
);

export default api;
"""

        # Auth service
        if self._has_authentication():
            files[
                "frontend/src/services/authService.js"
            ] = """import api from './api';

export const signup = async (userData) => {
  const response = await api.post('/api/auth/signup', userData);
  if (response.data.access_token) {
    localStorage.setItem('access_token', response.data.access_token);
    localStorage.setItem('refresh_token', response.data.refresh_token);
  }
  return response.data;
};

export const login = async (credentials) => {
  const response = await api.post('/api/auth/login', credentials);
  if (response.data.access_token) {
    localStorage.setItem('access_token', response.data.access_token);
    localStorage.setItem('refresh_token', response.data.refresh_token);
  }
  return response.data;
};

export const logout = async () => {
  try {
    await api.post('/api/auth/logout');
  } catch (error) {
    console.error('Logout error:', error);
  } finally {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
  }
};

export const checkAuth = async () => {
  const response = await api.get('/api/auth/me');
  return response.data;
};

export const getCurrentUser = () => {
  return checkAuth();
};

export const isAuthenticated = () => {
  return !!localStorage.getItem('access_token');
};
"""

        # Resource services
        tables = self.plan.get("database_schema", {}).get("tables", [])
        for table in tables:
            table_name = table["table_name"]
            if table_name == "users":
                continue

            class_name = self._to_class_name(table_name)
            singular = self._singularize(table_name)

            files[
                f"frontend/src/services/{singular}Service.js"
            ] = f"""import api from './api';

export const getAll{class_name} = async (page = 1, perPage = 20) => {{
  const response = await api.get('/api/{table_name}', {{
    params: {{ page, per_page: perPage }},
  }});
  return response.data;
}};

export const get{class_name}ById = async (id) => {{
  const response = await api.get(`/api/{table_name}/${{id}}`);
  return response.data;
}};

export const create{class_name} = async (data) => {{
  const response = await api.post('/api/{table_name}', data);
  return response.data;
}};

export const update{class_name} = async (id, data) => {{
  const response = await api.put(`/api/{table_name}/${{id}}`, data);
  return response.data;
}};

export const delete{class_name} = async (id) => {{
  const response = await api.delete(`/api/{table_name}/${{id}}`);
  return response.data;
}};
"""

        return files

    def _generate_auth_components(self) -> Dict[str, str]:
        """Generate authentication components"""
        files = {}

        # Login component
        files[
            "frontend/src/components/Auth/Login.jsx"
        ] = """import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { login } from '../../services/authService';
import './Auth.css';

const Login = () => {
  const [formData, setFormData] = useState({
    email: '',
    password: '',
  });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleChange = (e) => {
    setFormData({
      ...formData,
      [e.target.name]: e.target.value,
    });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      await login(formData);
      navigate('/');
    } catch (err) {
      setError(err.response?.data?.error || 'Login failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-container">
      <div className="auth-card">
        <h2>Login</h2>
        {{error && <div className="error-message">{{error}}</div>}}
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="email">Email</label>
            <input
              type="email"
              id="email"
              name="email"
              value={formData.email}
              onChange={handleChange}
              required
            />
          </div>
          <div className="form-group">
            <label htmlFor="password">Password</label>
            <input
              type="password"
              id="password"
              name="password"
              value={formData.password}
              onChange={handleChange}
              required
            />
          </div>
          <button type="submit" disabled={loading} className="btn-primary">
            {loading ? 'Logging in...' : 'Login'}
          </button>
        </form>
        <p className="auth-link">
          Don't have an account? <Link to="/signup">Sign up</Link>
        </p>
      </div>
    </div>
  );
};

export default Login;
"""

        # Signup component
        files[
            "frontend/src/components/Auth/Signup.jsx"
        ] = """import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { signup } from '../../services/authService';
import './Auth.css';

const Signup = () => {
  const [formData, setFormData] = useState({
    username: '',
    email: '',
    password: '',
    confirmPassword: '',
  });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleChange = (e) => {
    setFormData({
      ...formData,
      [e.target.name]: e.target.value,
    });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (formData.password !== formData.confirmPassword) {
      setError('Passwords do not match');
      return;
    }

    if (formData.password.length < 8) {
      setError('Password must be at least 8 characters');
      return;
    }

    setLoading(true);

    try {
      const { confirmPassword, ...signupData } = formData;
      await signup(signupData);
      navigate('/');
    } catch (err) {
      setError(err.response?.data?.error || 'Signup failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-container">
      <div className="auth-card">
        <h2>Sign Up</h2>
        {{error && <div className="error-message">{{error}}</div>}}
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="username">Username</label>
            <input
              type="text"
              id="username"
              name="username"
              value={formData.username}
              onChange={handleChange}
              required
            />
          </div>
          <div className="form-group">
            <label htmlFor="email">Email</label>
            <input
              type="email"
              id="email"
              name="email"
              value={formData.email}
              onChange={handleChange}
              required
            />
          </div>
          <div className="form-group">
            <label htmlFor="password">Password</label>
            <input
              type="password"
              id="password"
              name="password"
              value={formData.password}
              onChange={handleChange}
              required
              minLength="8"
            />
          </div>
          <div className="form-group">
            <label htmlFor="confirmPassword">Confirm Password</label>
            <input
              type="password"
              id="confirmPassword"
              name="confirmPassword"
              value={formData.confirmPassword}
              onChange={handleChange}
              required
            />
          </div>
          <button type="submit" disabled={loading} className="btn-primary">
            {loading ? 'Creating account...' : 'Sign Up'}
          </button>
        </form>
        <p className="auth-link">
          Already have an account? <Link to="/login">Login</Link>
        </p>
      </div>
    </div>
  );
};

export default Signup;
"""

        # Auth CSS
        files[
            "frontend/src/components/Auth/Auth.css"
        ] = """.auth-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 80vh;
  padding: 20px;
}

.auth-card {
  background: white;
  padding: 40px;
  border-radius: 8px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
  width: 100%;
  max-width: 400px;
}

.auth-card h2 {
  margin-bottom: 24px;
  text-align: center;
  color: #333;
}

.form-group {
  margin-bottom: 20px;
}

.form-group label {
  display: block;
  margin-bottom: 8px;
  font-weight: 500;
  color: #555;
}

.form-group input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 14px;
}

.form-group input:focus {
  outline: none;
  border-color: #007bff;
}

.error-message {
  background: #fee;
  color: #c33;
  padding: 12px;
  border-radius: 4px;
  margin-bottom: 20px;
  font-size: 14px;
}

.btn-primary {
  width: 100%;
  padding: 12px;
  background: #007bff;
  color: white;
  border: none;
  border-radius: 4px;
  font-size: 16px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s;
}

.btn-primary:hover:not(:disabled) {
  background: #0056b3;
}

.btn-primary:disabled {
  background: #ccc;
  cursor: not-allowed;
}

.auth-link {
  text-align: center;
  margin-top: 20px;
  color: #666;
}

.auth-link a {
  color: #007bff;
  text-decoration: none;
}

.auth-link a:hover {
  text-decoration: underline;
}
"""

        # PrivateRoute component
        files[
            "frontend/src/components/Auth/PrivateRoute.jsx"
        ] = """import React from 'react';
import { Navigate } from 'react-router-dom';
import { isAuthenticated } from '../../services/authService';

const PrivateRoute = ({ children }) => {
  return isAuthenticated() ? children : <Navigate to="/login" replace />;
};

export default PrivateRoute;
"""

        return files

    def _generate_crud_components(self) -> Dict[str, str]:
        """Generate CRUD components for each resource"""
        files = {}
        tables = self.plan.get("database_schema", {}).get("tables", [])

        for table in tables:
            table_name = table["table_name"]
            if table_name == "users":
                continue

            class_name = self._to_class_name(table_name)
            singular = self._singularize(table_name)
            columns = table.get("columns", [])

            # List component
            files[f"frontend/src/components/{class_name}/{class_name}List.jsx"] = self._generate_list_component(
                class_name, singular, table_name, columns
            )

            # Form component
            files[f"frontend/src/components/{class_name}/{class_name}Form.jsx"] = self._generate_form_component(
                class_name, singular, table_name, columns
            )

            # Detail component
            files[f"frontend/src/components/{class_name}/{class_name}Detail.jsx"] = self._generate_detail_component(
                class_name, singular, table_name, columns
            )

            # CSS
            files[f"frontend/src/components/{class_name}/{class_name}.css"] = self._generate_component_css(class_name)

        return files

    def _generate_list_component(self, class_name: str, singular: str, table_name: str, columns: List) -> str:
        """Generate list component for a resource"""
        # Get display columns (exclude password, timestamps, foreign keys)
        display_cols = [col for col in columns if not any(x in col["name"] for x in ["password", "_id", "hash"])][:5]

        return f"""import React, {{ useState, useEffect }} from 'react';
import {{ Link }} from 'react-router-dom';
import {{ getAll{class_name}, delete{class_name} }} from '../../services/{singular}Service';
import './{class_name}.css';

const {class_name}List = () => {{
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [page, setPage] = useState(1);
  const [pagination, setPagination] = useState(null);

  useEffect(() => {{
    loadItems();
  }}, [page]);

  const loadItems = async () => {{
    try {{
      setLoading(true);
      const response = await getAll{class_name}(page);
      setItems(response.data);
      setPagination(response.pagination);
    }} catch (err) {{
      setError('Failed to load {table_name}');
      console.error(err);
    }} finally {{
      setLoading(false);
    }}
  }};

  const handleDelete = async (id) => {{
    if (window.confirm('Are you sure you want to delete this item?')) {{
      try {{
        await delete{class_name}(id);
        loadItems(); // Reload list
      }} catch (err) {{
        alert('Failed to delete item');
        console.error(err);
      }}
    }}
  }};

  if (loading) return <div className="loading">Loading...</div>;
  if (error) return <div className="error">{{error}}</div>;

  return (
    <div className="list-container">
      <div className="list-header">
        <h2>{class_name} List</h2>
        <Link to="/{table_name}/new" className="btn-primary">
          Add New
        </Link>
      </div>

      <div className="table-container">
        <table>
          <thead>
            <tr>
{chr(10).join(f'              <th>{col["name"].replace("_", " ").title()}</th>' for col in display_cols[:5])}
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {{items.length === 0 ? (
              <tr>
                <td colSpan="{len(display_cols) + 1}" className="no-data">
                  No {table_name} found
                </td>
              </tr>
            ) : (
              items.map((item) => (
                <tr key={{item.id}}>
{chr(10).join(f'                  <td>{{item.{col["name"]}}}</td>' for col in display_cols[:5])}
                  <td className="actions">
                    <Link to={{`/{table_name}/${{item.id}}`}} className="btn-view">
                      View
                    </Link>
                    <Link to={{`/{table_name}/${{item.id}}/edit`}} className="btn-edit">
                      Edit
                    </Link>
                    <button
                      onClick={{() => handleDelete(item.id)}}
                      className="btn-delete"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))
            )}}
          </tbody>
        </table>
      </div>

      {{pagination && pagination.pages > 1 && (
        <div className="pagination">
          <button
            onClick={{() => setPage(page - 1)}}
            disabled={{page === 1}}
            className="btn-page"
          >
            Previous
          </button>
          <span>
            Page {{page}} of {{pagination.pages}}
          </span>
          <button
            onClick={{() => setPage(page + 1)}}
            disabled={{page === pagination.pages}}
            className="btn-page"
          >
            Next
          </button>
        </div>
      )}}
    </div>
  );
}};

export default {class_name}List;
"""

    def _generate_form_component(self, class_name: str, singular: str, table_name: str, columns: List) -> str:
        """Generate form component for a resource"""
        # Get editable columns (exclude id, timestamps, foreign keys, password)
        editable_cols = [
            col
            for col in columns
            if not any(x in col["name"] for x in ["id", "created", "updated", "password", "hash"])
        ]

        return f"""import React, {{ useState, useEffect }} from 'react';
import {{ useNavigate, useParams }} from 'react-router-dom';
import {{ create{class_name}, update{class_name}, get{class_name}ById }} from '../../services/{singular}Service';
import './{class_name}.css';

const {class_name}Form = () => {{
  const {{ id }} = useParams();
  const navigate = useNavigate();
  const isEdit = !!id;

  const [formData, setFormData] = useState({{
{chr(10).join(f'    {col["name"]}: "",' for col in editable_cols)}
  }});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {{
    if (isEdit) {{
      loadItem();
    }}
  }}, [id]);

  const loadItem = async () => {{
    try {{
      const response = await get{class_name}ById(id);
      setFormData(response.data);
    }} catch (err) {{
      setError('Failed to load {singular}');
      console.error(err);
    }}
  }};

  const handleChange = (e) => {{
    setFormData({{
      ...formData,
      [e.target.name]: e.target.value,
    }});
  }};

  const handleSubmit = async (e) => {{
    e.preventDefault();
    setError('');
    setLoading(true);

    try {{
      if (isEdit) {{
        await update{class_name}(id, formData);
      }} else {{
        await create{class_name}(formData);
      }}
      navigate('/{table_name}');
    }} catch (err) {{
      setError(err.response?.data?.error || 'Failed to save {singular}');
    }} finally {{
      setLoading(false);
    }}
  }};

  return (
    <div className="form-container">
      <h2>{{isEdit ? 'Edit' : 'Create'}} {class_name}</h2>
      {{error && <div className="error-message">{{error}}</div>}}

      <form onSubmit={{handleSubmit}}>
{chr(10).join(self._generate_form_field(col) for col in editable_cols)}

        <div className="form-actions">
          <button type="submit" disabled={{loading}} className="btn-primary">
            {{loading ? 'Saving...' : 'Save'}}
          </button>
          <button
            type="button"
            onClick={{() => navigate('/{table_name}')}}
            className="btn-secondary"
          >
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}};

export default {class_name}Form;
"""

    def _generate_form_field(self, col: Dict) -> str:
        """Generate a form field based on column type"""
        col_name = col["name"]
        col_type = col["type"].upper()
        label = col_name.replace("_", " ").title()

        if "TEXT" in col_type:
            return f"""        <div className="form-group">
          <label htmlFor="{col_name}">{label}</label>
          <textarea
            id="{col_name}"
            name="{col_name}"
            value={{formData.{col_name}}}
            onChange={{handleChange}}
            rows="4"
          />
        </div>"""
        elif "BOOLEAN" in col_type or "BOOL" in col_type:
            return f"""        <div className="form-group">
          <label className="checkbox-label">
            <input
              type="checkbox"
              name="{col_name}"
              checked={{formData.{col_name}}}
              onChange={{(e) => setFormData({{...formData, {col_name}: e.target.checked}})}}
            />
            {label}
          </label>
        </div>"""
        else:
            input_type = "number" if any(x in col_type for x in ["INT", "DECIMAL", "FLOAT"]) else "text"
            return f"""        <div className="form-group">
          <label htmlFor="{col_name}">{label}</label>
          <input
            type="{input_type}"
            id="{col_name}"
            name="{col_name}"
            value={{formData.{col_name}}}
            onChange={{handleChange}}
            required
          />
        </div>"""

    def _generate_detail_component(self, class_name: str, singular: str, table_name: str, columns: List) -> str:
        """Generate detail component for a resource"""
        display_cols = [col for col in columns if not any(x in col["name"] for x in ["password", "hash"])]

        return f"""import React, {{ useState, useEffect }} from 'react';
import {{ useParams, useNavigate, Link }} from 'react-router-dom';
import {{ get{class_name}ById, delete{class_name} }} from '../../services/{singular}Service';
import './{class_name}.css';

const {class_name}Detail = () => {{
  const {{ id }} = useParams();
  const navigate = useNavigate();
  const [item, setItem] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {{
    loadItem();
  }}, [id]);

  const loadItem = async () => {{
    try {{
      const response = await get{class_name}ById(id);
      setItem(response.data);
    }} catch (err) {{
      setError('Failed to load {singular}');
      console.error(err);
    }} finally {{
      setLoading(false);
    }}
  }};

  const handleDelete = async () => {{
    if (window.confirm('Are you sure you want to delete this item?')) {{
      try {{
        await delete{class_name}(id);
        navigate('/{table_name}');
      }} catch (err) {{
        alert('Failed to delete item');
        console.error(err);
      }}
    }}
  }};

  if (loading) return <div className="loading">Loading...</div>;
  if (error) return <div className="error">{{error}}</div>;
  if (!item) return <div>Not found</div>;

  return (
    <div className="detail-container">
      <div className="detail-header">
        <h2>{class_name} Details</h2>
        <div className="detail-actions">
          <Link to={{`/{table_name}/${{id}}/edit`}} className="btn-edit">
            Edit
          </Link>
          <button onClick={{handleDelete}} className="btn-delete">
            Delete
          </button>
          <Link to="/{table_name}" className="btn-secondary">
            Back to List
          </Link>
        </div>
      </div>

      <div className="detail-content">
{chr(10).join(f'''        <div className="detail-field">
          <label>{col["name"].replace("_", " ").title()}:</label>
          <span>{{item.{col["name"]}}}</span>
        </div>''' for col in display_cols)}
      </div>
    </div>
  );
}};

export default {class_name}Detail;
"""

    def _generate_component_css(self, class_name: str) -> str:
        """Generate CSS for components"""
        return """.list-container, .form-container, .detail-container {
  padding: 20px;
  max-width: 1200px;
  margin: 0 auto;
}

.list-header, .detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.table-container {
  overflow-x: auto;
  background: white;
  border-radius: 8px;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

table {
  width: 100%;
  border-collapse: collapse;
}

thead {
  background: #f8f9fa;
}

th, td {
  padding: 12px 16px;
  text-align: left;
  border-bottom: 1px solid #dee2e6;
}

th {
  font-weight: 600;
  color: #495057;
}

.no-data {
  text-align: center;
  color: #6c757d;
  padding: 40px !important;
}

.actions {
  display: flex;
  gap: 8px;
}

.btn-primary, .btn-secondary, .btn-edit, .btn-delete, .btn-view, .btn-page {
  padding: 8px 16px;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  text-decoration: none;
  display: inline-block;
  transition: all 0.2s;
}

.btn-primary {
  background: #007bff;
  color: white;
}

.btn-primary:hover:not(:disabled) {
  background: #0056b3;
}

.btn-secondary {
  background: #6c757d;
  color: white;
}

.btn-edit {
  background: #28a745;
  color: white;
}

.btn-delete {
  background: #dc3545;
  color: white;
}

.btn-view {
  background: #17a2b8;
  color: white;
}

.pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 16px;
  margin-top: 24px;
}

.btn-page:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.form-group {
  margin-bottom: 20px;
}

.form-group label {
  display: block;
  margin-bottom: 8px;
  font-weight: 500;
  color: #495057;
}

.form-group input, .form-group textarea, .form-group select {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #ced4da;
  border-radius: 4px;
  font-size: 14px;
}

.form-actions {
  display: flex;
  gap: 12px;
  margin-top: 24px;
}

.detail-content {
  background: white;
  padding: 24px;
  border-radius: 8px;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.detail-field {
  margin-bottom: 16px;
  display: flex;
  gap: 12px;
}

.detail-field label {
  font-weight: 600;
  color: #495057;
  min-width: 150px;
}

.detail-field span {
  color: #212529;
}

.loading, .error {
  text-align: center;
  padding: 40px;
}

.error-message {
  background: #f8d7da;
  color: #721c24;
  padding: 12px;
  border-radius: 4px;
  margin-bottom: 20px;
}

.detail-actions {
  display: flex;
  gap: 8px;
}
"""

    def _generate_layout_components(self) -> Dict[str, str]:
        """Generate layout components"""
        files = {}

        # Layout component
        has_auth = self._has_authentication()
        files[
            "frontend/src/components/Layout/Layout.jsx"
        ] = f"""import React from 'react';
import Header from './Header';
import './Layout.css';

const Layout = ({{ children }}) => {{
  return (
    <div className="layout">
      <Header />
      <main className="main-content">
        {{children}}
      </main>
      <footer className="footer">
        <p>&copy; 2026 {{process.env.REACT_APP_NAME || 'App'}}. All rights reserved.</p>
      </footer>
    </div>
  );
}};

export default Layout;
"""

        # Header component
        tables = self.plan.get("database_schema", {}).get("tables", [])
        nav_items = [t["table_name"] for t in tables if t["table_name"] != "users"]

        files[
            "frontend/src/components/Layout/Header.jsx"
        ] = f"""import React from 'react';
import {{ Link, useNavigate }} from 'react-router-dom';
import {{ isAuthenticated, logout }} from '../../services/authService';
import './Layout.css';

const Header = () => {{
  const navigate = useNavigate();
  const authenticated = isAuthenticated();

  const handleLogout = async () => {{
    await logout();
    navigate('/login');
  }};

  return (
    <header className="header">
      <div className="header-content">
        <Link to="/" className="logo">
          {{process.env.REACT_APP_NAME || 'App'}}
        </Link>
        <nav className="nav">
          {{authenticated && (
            <>
{chr(10).join(f'              <Link to="/{item}">{item.title()}</Link>' for item in nav_items[:4])}
            </>
          )}}
        </nav>
        <div className="auth-buttons">
          {{authenticated ? (
            <button onClick={{handleLogout}} className="btn-logout">
              Logout
            </button>
          ) : (
            <>
              <Link to="/login" className="btn-login">
                Login
              </Link>
              <Link to="/signup" className="btn-signup">
                Sign Up
              </Link>
            </>
          )}}
        </div>
      </div>
    </header>
  );
}};

export default Header;
"""

        # Layout CSS
        files[
            "frontend/src/components/Layout/Layout.css"
        ] = """.layout {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.header {
  background: #fff;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
  position: sticky;
  top: 0;
  z-index: 100;
}

.header-content {
  max-width: 1200px;
  margin: 0 auto;
  padding: 16px 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.logo {
  font-size: 24px;
  font-weight: 700;
  color: #007bff;
  text-decoration: none;
}

.nav {
  display: flex;
  gap: 24px;
}

.nav a {
  color: #495057;
  text-decoration: none;
  font-weight: 500;
  transition: color 0.2s;
}

.nav a:hover {
  color: #007bff;
}

.auth-buttons {
  display: flex;
  gap: 12px;
}

.btn-login, .btn-signup, .btn-logout {
  padding: 8px 16px;
  border-radius: 4px;
  text-decoration: none;
  font-weight: 500;
  transition: all 0.2s;
  border: none;
  cursor: pointer;
}

.btn-login {
  color: #007bff;
  background: transparent;
}

.btn-signup {
  background: #007bff;
  color: white;
}

.btn-logout {
  background: #dc3545;
  color: white;
}

.main-content {
  flex: 1;
  padding: 20px;
  background: #f8f9fa;
}

.footer {
  background: #343a40;
  color: white;
  padding: 20px;
  text-align: center;
}
"""

        # Home component
        files[
            "frontend/src/components/Home/Home.jsx"
        ] = f"""import React from 'react';
import {{ Link }} from 'react-router-dom';
import './Home.css';

const Home = () => {{
  return (
    <div className="home-container">
      <h1>Welcome to {{process.env.REACT_APP_NAME || 'App'}}</h1>
      <p>Get started by exploring the following sections:</p>
      <div className="home-links">
{chr(10).join(f'''        <Link to="/{item}" className="home-link-card">
          <h3>{item.title()}</h3>
          <p>Manage {item}</p>
        </Link>''' for item in nav_items[:4])}
      </div>
    </div>
  );
}};

export default Home;
"""

        files[
            "frontend/src/components/Home/Home.css"
        ] = """.home-container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 40px 20px;
  text-align: center;
}

.home-container h1 {
  font-size: 36px;
  margin-bottom: 16px;
  color: #212529;
}

.home-container p {
  font-size: 18px;
  color: #6c757d;
  margin-bottom: 40px;
}

.home-links {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 24px;
  margin-top: 40px;
}

.home-link-card {
  background: white;
  padding: 32px;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  text-decoration: none;
  color: inherit;
  transition: transform 0.2s, box-shadow 0.2s;
}

.home-link-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.home-link-card h3 {
  font-size: 24px;
  color: #007bff;
  margin-bottom: 8px;
}

.home-link-card p {
  color: #6c757d;
  margin: 0;
}
"""

        return files

    def _generate_state_management(self) -> Dict[str, str]:
        """Generate state management files"""
        files = {}
        state_mgmt = self.architecture.get("state_management", {}).get("pattern", {})
        uses_redux = "Redux" in state_mgmt.get("name", "")

        if uses_redux:
            # Redux store
            files[
                "frontend/src/store/store.js"
            ] = """import { configureStore } from '@reduxjs/toolkit';
import authReducer from './slices/authSlice';

export const store = configureStore({
  reducer: {
    auth: authReducer,
  },
});

export default store;
"""

            # Auth slice
            files[
                "frontend/src/store/slices/authSlice.js"
            ] = """import { createSlice } from '@reduxjs/toolkit';

const initialState = {
  user: null,
  token: localStorage.getItem('access_token'),
  isAuthenticated: !!localStorage.getItem('access_token'),
};

export const authSlice = createSlice({
  name: 'auth',
  initialState,
  reducers: {
    setUser: (state, action) => {
      state.user = action.payload;
      state.isAuthenticated = true;
    },
    setToken: (state, action) => {
      state.token = action.payload;
      state.isAuthenticated = !!action.payload;
    },
    logout: (state) => {
      state.user = null;
      state.token = null;
      state.isAuthenticated = false;
    },
  },
});

export const { setUser, setToken, logout } = authSlice.actions;
export default authSlice.reducer;
"""
        else:
            # Context API
            files[
                "frontend/src/context/AuthContext.jsx"
            ] = """import React, { createContext, useState, useContext, useEffect } from 'react';
import { getCurrentUser, isAuthenticated } from '../services/authService';

const AuthContext = createContext();

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
};

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (isAuthenticated()) {
      loadUser();
    } else {
      setLoading(false);
    }
  }, []);

  const loadUser = async () => {
    try {
      const response = await getCurrentUser();
      setUser(response.user);
    } catch (error) {
      console.error('Failed to load user:', error);
    } finally {
      setLoading(false);
    }
  };

  const value = {
    user,
    setUser,
    loading,
    isAuthenticated: isAuthenticated(),
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};
"""

        return files

    def _generate_react_routing(self) -> str:
        """Generate React Router configuration"""
        has_auth = self._has_authentication()
        tables = self.plan.get("database_schema", {}).get("tables", [])
        resources = [t["table_name"] for t in tables if t["table_name"] != "users"]

        # Import statements
        imports = [
            'import React from "react";',
            'import { Routes, Route, Navigate } from "react-router-dom";',
            'import Home from "../components/Home/Home";',
        ]

        if has_auth:
            imports.extend(
                [
                    'import Login from "../components/Auth/Login";',
                    'import Signup from "../components/Auth/Signup";',
                    'import PrivateRoute from "../components/Auth/PrivateRoute";',
                ]
            )

        for table_name in resources:
            class_name = self._to_class_name(table_name)
            imports.extend(
                [
                    f'import {class_name}List from "../components/{class_name}/{class_name}List";',
                    f'import {class_name}Form from "../components/{class_name}/{class_name}Form";',
                    f'import {class_name}Detail from "../components/{class_name}/{class_name}Detail";',
                ]
            )

        # Routes
        route_lines = []
        route_lines.append('      <Route path="/" element={<Home />} />')

        if has_auth:
            route_lines.extend(
                [
                    '      <Route path="/login" element={<Login />} />',
                    '      <Route path="/signup" element={<Signup />} />',
                ]
            )

        for table_name in resources:
            class_name = self._to_class_name(table_name)
            if has_auth:
                route_lines.extend(
                    [
                        f'      <Route path="/{table_name}" element={{<PrivateRoute><{class_name}List /></PrivateRoute>}} />',
                        f'      <Route path="/{table_name}/new" element={{<PrivateRoute><{class_name}Form /></PrivateRoute>}} />',
                        f'      <Route path="/{table_name}/:id" element={{<PrivateRoute><{class_name}Detail /></PrivateRoute>}} />',
                        f'      <Route path="/{table_name}/:id/edit" element={{<PrivateRoute><{class_name}Form /></PrivateRoute>}} />',
                    ]
                )
            else:
                route_lines.extend(
                    [
                        f'      <Route path="/{table_name}" element={{<{class_name}List />}} />',
                        f'      <Route path="/{table_name}/new" element={{<{class_name}Form />}} />',
                        f'      <Route path="/{table_name}/:id" element={{<{class_name}Detail />}} />',
                        f'      <Route path="/{table_name}/:id/edit" element={{<{class_name}Form />}} />',
                    ]
                )

        return f"""{chr(10).join(imports)}

const AppRoutes = () => {{
  return (
    <Routes>
{chr(10).join(route_lines)}
      <Route path="*" element={{<Navigate to="/" replace />}} />
    </Routes>
  );
}};

export default AppRoutes;
"""

    def _generate_styles(self) -> Dict[str, str]:
        """Generate style files"""
        files = {}

        # Main CSS
        files[
            "frontend/src/index.css"
        ] = """* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen',
    'Ubuntu', 'Cantarell', 'Fira Sans', 'Droid Sans', 'Helvetica Neue',
    sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  background: #f8f9fa;
  color: #212529;
}

code {
  font-family: source-code-pro, Menlo, Monaco, Consolas, 'Courier New',
    monospace;
}

a {
  color: #007bff;
  text-decoration: none;
}

a:hover {
  text-decoration: underline;
}
"""

        files[
            "frontend/src/App.css"
        ] = """.App {
  min-height: 100vh;
}
"""

        return files

    def _generate_frontend_env(self) -> str:
        """Generate .env.example"""
        return """# API Configuration
REACT_APP_API_URL=http://localhost:5000

# App Name
REACT_APP_NAME=App
"""

    def _generate_frontend_readme(self, framework: str) -> str:
        """Generate README for frontend"""
        project_name = self.plan.get("name", "App")

        return f"""# {project_name} - Frontend

{framework} frontend application for {project_name}.

## Setup

### 1. Install Dependencies

```bash
npm install
```

### 2. Configure Environment

Copy `.env.example` to `.env` and update the values:

```bash
cp .env.example .env
```

Make sure `REACT_APP_API_URL` points to your backend API.

### 3. Run the Development Server

```bash
npm start
```

The app will open at [http://localhost:3000](http://localhost:3000).

## Available Scripts

- `npm start` - Run development server
- `npm build` - Build for production
- `npm test` - Run tests
- `npm eject` - Eject from Create React App (irreversible)

## Project Structure

```
frontend/
├── public/
│   └── index.html
├── src/
│   ├── components/     # React components
│   ├── services/       # API services
│   ├── routes/         # Routing configuration
│   ├── store/          # State management
│   ├── App.js
│   └── index.js
└── package.json
```

## Features

- React Router for navigation
- Axios for API calls
- JWT authentication
- Responsive design
- CRUD operations for all resources

## Building for Production

```bash
npm run build
```

The build folder will contain the optimized production build.

## Deployment

Deploy the `build` folder to any static hosting service:
- Vercel
- Netlify
- AWS S3
- GitHub Pages
"""

    def _generate_gitignore(self) -> str:
        """Generate .gitignore"""
        return """# Dependencies
/node_modules
/.pnp
.pnp.js

# Testing
/coverage

# Production
/build

# Misc
.DS_Store
.env.local
.env.development.local
.env.test.local
.env.production.local

npm-debug.log*
yarn-debug.log*
yarn-error.log*

# Environment
.env
"""

    # ========================================================================
    # VUE FRONTEND GENERATION
    # ========================================================================

    async def _generate_vue_frontend(self) -> Dict[str, Any]:
        """Generate complete Vue frontend"""
        print("[Frontend Generator] Vue frontend generation not yet implemented")
        print("[Frontend Generator] ℹ️  Falling back to React generation")
        return await self._generate_react_frontend()

    # ========================================================================
    # UTILITY METHODS
    # ========================================================================

    def _has_authentication(self) -> bool:
        """Check if authentication is needed"""
        tables = self.plan.get("database_schema", {}).get("tables", [])
        return any(t["table_name"] == "users" for t in tables)

    def _to_class_name(self, table_name: str) -> str:
        """Convert table name to class name (PascalCase)"""
        singular = self._singularize(table_name)
        return "".join(word.capitalize() for word in singular.split("_"))

    def _singularize(self, word: str) -> str:
        """Simple singularize (remove trailing 's')"""
        if word.endswith("ies"):
            return word[:-3] + "y"
        elif word.endswith("ses"):
            return word[:-2]
        elif word.endswith("s"):
            return word[:-1]
        return word

    def _get_file_type(self, path: str) -> str:
        """Get file type from path"""
        if path.endswith(".jsx") or path.endswith(".js"):
            return "javascript"
        elif path.endswith(".css"):
            return "css"
        elif path.endswith(".json"):
            return "json"
        elif path.endswith(".html"):
            return "html"
        elif path.endswith(".md"):
            return "markdown"
        else:
            return "text"

    def _get_file_structure(self, files: Dict[str, str]) -> Dict:
        """Generate file structure tree"""
        structure = {}
        for path in files.keys():
            parts = path.split("/")
            current = structure
            for part in parts:
                if part not in current:
                    current[part] = {}
                current = current[part]
        return structure

    async def save_to_database(self, db_connection=None) -> bool:
        """
        Save generated files to database

        Args:
            db_connection: Optional database connection

        Returns:
            bool: True if saved successfully
        """
        if not self.generated_files:
            print("[Frontend Generator] ⚠️ No files to save")
            return False

        if db_connection is None and not DB_AVAILABLE:
            print("[Frontend Generator] ⚠️ Database not available, skipping save")
            return False

        if db_connection is None:
            db_connection = db

        try:
            with db_connection.engine.connect() as conn:
                for file_data in self.generated_files:
                    # Insert file record
                    insert_query = """
                        INSERT INTO app_builder_files
                        (project_id, file_path, content, file_type, version, is_latest, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, NOW())
                    """

                    conn.execute(
                        db_connection.text(insert_query),
                        (
                            self.project_id,
                            file_data["file_path"],
                            file_data["content"],
                            file_data["file_type"],
                            1,  # version
                            True,  # is_latest
                        ),
                    )

                conn.commit()
                print(f"[Frontend Generator] ✅ Saved {len(self.generated_files)} files to database")
                return True

        except Exception as e:
            print(f"[Frontend Generator] ❌ Failed to save to database: {e}")
            return False


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    import asyncio

    print("=" * 80)
    print("FRONTEND GENERATOR TEST")
    print("=" * 80)

    # Mock plan
    mock_plan = {
        "name": "Todo App",
        "tech_stack": {
            "backend": "Flask",
            "frontend": "React",
            "database": "PostgreSQL",
        },
        "database_schema": {
            "database_type": "PostgreSQL",
            "tables": [
                {
                    "table_name": "users",
                    "columns": [
                        {"name": "id", "type": "SERIAL PRIMARY KEY"},
                        {"name": "username", "type": "VARCHAR(100)"},
                        {"name": "email", "type": "VARCHAR(255)"},
                    ],
                },
                {
                    "table_name": "tasks",
                    "columns": [
                        {"name": "id", "type": "SERIAL PRIMARY KEY"},
                        {"name": "user_id", "type": "INTEGER REFERENCES users(id)"},
                        {"name": "title", "type": "VARCHAR(255)"},
                        {"name": "description", "type": "TEXT"},
                        {"name": "completed", "type": "BOOLEAN DEFAULT FALSE"},
                    ],
                },
            ],
        },
    }

    mock_architecture = {"state_management": {"pattern": {"name": "React Context API"}}}

    async def test_frontend():
        print("\nTest 1: React Frontend Generation")
        print("-" * 80)

        generator = FrontendGenerator(project_id=1, plan=mock_plan, architecture=mock_architecture)
        result = await generator.generate_frontend()

        print(f"\n📊 Generation Summary:")
        print(f"  - Framework: {result['framework']}")
        print(f"  - Files Generated: {result['file_count']}")
        print(f"  - Generated At: {result['generated_at']}")

        print(f"\n📁 File Structure:")
        for file in result["files"][:15]:  # Show first 15 files
            print(f"  - {file['file_path']} ({file['file_type']})")

        if len(result["files"]) > 15:
            print(f"  ... and {len(result['files']) - 15} more files")

        print(f"\n✅ Frontend Generator test complete")

    asyncio.run(test_frontend())

    print("\n" + "=" * 80)
