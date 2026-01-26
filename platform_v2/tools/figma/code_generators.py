"""
Figma Code Generators - Phase 44
================================
Generate React, Vue, and HTML code from parsed Figma designs.
"""
import os
import json
import logging
import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)


def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        port=os.getenv('DB_PORT', '5432'),
        database=os.getenv('DB_NAME', 'archie'),
        user=os.getenv('DB_USER', 'archie'),
        password=os.getenv('DB_PASSWORD', '')
    )


def get_parsed_design(parse_id):
    """Fetch parsed design from database"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            SELECT fpd.*, fi.figma_file_name
            FROM figma_parsed_designs fpd
            JOIN figma_imports fi ON fpd.import_id = fi.id
            WHERE fpd.id = %s
        """, (parse_id,))

        design = cur.fetchone()
        cur.close()
        conn.close()
        return design
    except Exception as e:
        logger.error(f"Failed to get parsed design: {e}")
        return None


def get_component_mappings(parse_id):
    """Fetch component mappings for a parsed design"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            SELECT * FROM figma_component_mappings
            WHERE parsed_design_id = %s
            ORDER BY component_type, suggested_component_name
        """, (parse_id,))

        mappings = cur.fetchall()
        cur.close()
        conn.close()
        return mappings
    except Exception as e:
        logger.error(f"Failed to get component mappings: {e}")
        return []


# =============================================================================
# STYLE GENERATORS
# =============================================================================

def generate_tailwind_classes(styles):
    """Convert Figma styles to Tailwind classes"""
    classes = []

    if not styles:
        return ""

    # Background color
    if 'backgroundColor' in styles:
        color = styles['backgroundColor']
        if color.startswith('#'):
            classes.append(f"bg-[{color}]")

    # Text color
    if 'color' in styles:
        color = styles['color']
        if color.startswith('#'):
            classes.append(f"text-[{color}]")

    # Font size
    if 'fontSize' in styles:
        size = styles['fontSize']
        size_map = {
            12: 'text-xs', 14: 'text-sm', 16: 'text-base',
            18: 'text-lg', 20: 'text-xl', 24: 'text-2xl',
            30: 'text-3xl', 36: 'text-4xl', 48: 'text-5xl'
        }
        classes.append(size_map.get(size, f"text-[{size}px]"))

    # Font weight
    if 'fontWeight' in styles:
        weight = styles['fontWeight']
        weight_map = {
            300: 'font-light', 400: 'font-normal', 500: 'font-medium',
            600: 'font-semibold', 700: 'font-bold', 800: 'font-extrabold'
        }
        classes.append(weight_map.get(weight, f"font-[{weight}]"))

    # Padding
    if 'padding' in styles:
        p = styles['padding']
        if isinstance(p, dict):
            if p.get('top') == p.get('bottom') == p.get('left') == p.get('right'):
                classes.append(f"p-[{p['top']}px]")
            else:
                classes.append(f"pt-[{p.get('top', 0)}px] pb-[{p.get('bottom', 0)}px] pl-[{p.get('left', 0)}px] pr-[{p.get('right', 0)}px]")
        else:
            classes.append(f"p-[{p}px]")

    # Border radius
    if 'borderRadius' in styles:
        r = styles['borderRadius']
        radius_map = {0: 'rounded-none', 4: 'rounded', 8: 'rounded-lg',
                      12: 'rounded-xl', 16: 'rounded-2xl', 9999: 'rounded-full'}
        classes.append(radius_map.get(r, f"rounded-[{r}px]"))

    # Width/Height
    if 'width' in styles and styles['width'] != 'auto':
        classes.append(f"w-[{styles['width']}px]")
    if 'height' in styles and styles['height'] != 'auto':
        classes.append(f"h-[{styles['height']}px]")

    # Flexbox
    if styles.get('display') == 'flex':
        classes.append('flex')
        if styles.get('flexDirection') == 'column':
            classes.append('flex-col')
        if styles.get('alignItems'):
            align_map = {'center': 'items-center', 'flex-start': 'items-start', 'flex-end': 'items-end'}
            classes.append(align_map.get(styles['alignItems'], ''))
        if styles.get('justifyContent'):
            justify_map = {'center': 'justify-center', 'flex-start': 'justify-start',
                          'flex-end': 'justify-end', 'space-between': 'justify-between'}
            classes.append(justify_map.get(styles['justifyContent'], ''))
        if styles.get('gap'):
            classes.append(f"gap-[{styles['gap']}px]")

    return ' '.join(filter(None, classes))


def generate_css_styles(styles, class_name):
    """Convert Figma styles to CSS"""
    if not styles:
        return ""

    css_props = []

    if 'backgroundColor' in styles:
        css_props.append(f"  background-color: {styles['backgroundColor']};")
    if 'color' in styles:
        css_props.append(f"  color: {styles['color']};")
    if 'fontSize' in styles:
        css_props.append(f"  font-size: {styles['fontSize']}px;")
    if 'fontWeight' in styles:
        css_props.append(f"  font-weight: {styles['fontWeight']};")
    if 'fontFamily' in styles:
        css_props.append(f"  font-family: {styles['fontFamily']};")
    if 'padding' in styles:
        p = styles['padding']
        if isinstance(p, dict):
            css_props.append(f"  padding: {p.get('top', 0)}px {p.get('right', 0)}px {p.get('bottom', 0)}px {p.get('left', 0)}px;")
        else:
            css_props.append(f"  padding: {p}px;")
    if 'borderRadius' in styles:
        css_props.append(f"  border-radius: {styles['borderRadius']}px;")
    if 'width' in styles and styles['width'] != 'auto':
        css_props.append(f"  width: {styles['width']}px;")
    if 'height' in styles and styles['height'] != 'auto':
        css_props.append(f"  height: {styles['height']}px;")
    if styles.get('display') == 'flex':
        css_props.append("  display: flex;")
        if styles.get('flexDirection'):
            css_props.append(f"  flex-direction: {styles['flexDirection']};")
        if styles.get('alignItems'):
            css_props.append(f"  align-items: {styles['alignItems']};")
        if styles.get('justifyContent'):
            css_props.append(f"  justify-content: {styles['justifyContent']};")
        if styles.get('gap'):
            css_props.append(f"  gap: {styles['gap']}px;")

    if css_props:
        return f".{class_name} {{\n" + "\n".join(css_props) + "\n}\n"
    return ""


# =============================================================================
# REACT CODE GENERATOR
# =============================================================================

def generate_react_code(parse_id, styling='tailwind', components=None, options=None):
    """Generate React components from parsed Figma design"""
    options = options or {}
    files = []

    design = get_parsed_design(parse_id)
    if not design:
        return files

    mappings = get_component_mappings(parse_id)
    sections = design.get('sections') or []
    design_tokens = design.get('design_tokens') or {}

    # Filter components if specified
    if components:
        mappings = [m for m in mappings if m['figma_node_id'] in components]

    # Generate main App component
    app_imports = []
    app_components = []
    css_styles = []

    for mapping in mappings:
        comp_name = mapping.get('suggested_component_name', 'Component')
        comp_name = ''.join(word.capitalize() for word in comp_name.replace('-', '_').split('_'))
        comp_type = mapping.get('component_type', 'div')
        styles = mapping.get('styles') or {}
        props = mapping.get('props') or []

        # Generate component file
        if styling == 'tailwind':
            comp_content = generate_react_tailwind_component(comp_name, comp_type, styles, props)
        elif styling == 'styled-components':
            comp_content = generate_react_styled_component(comp_name, comp_type, styles, props)
        else:
            comp_content = generate_react_css_component(comp_name, comp_type, styles, props)
            css_styles.append(generate_css_styles(styles, comp_name.lower()))

        files.append({
            'path': f"components/{comp_name}.jsx",
            'language': 'jsx',
            'content': comp_content
        })

        app_imports.append(f"import {comp_name} from './components/{comp_name}';")
        app_components.append(f"      <{comp_name} />")

    # Generate App.jsx
    app_content = f'''import React from 'react';
{chr(10).join(app_imports)}
{"import './App.css';" if styling == 'css' else ""}

function App() {{
  return (
    <div className="app">
{chr(10).join(app_components)}
    </div>
  );
}}

export default App;
'''

    files.append({
        'path': 'App.jsx',
        'language': 'jsx',
        'content': app_content
    })

    # Generate CSS file if using CSS styling
    if styling == 'css' and css_styles:
        files.append({
            'path': 'App.css',
            'language': 'css',
            'content': '\n'.join(css_styles)
        })

    # Generate design tokens file
    if design_tokens:
        tokens_content = f'''// Design tokens extracted from Figma
export const colors = {json.dumps(design_tokens.get('colors', {}), indent=2)};

export const typography = {json.dumps(design_tokens.get('typography', {}), indent=2)};

export const spacing = {json.dumps(design_tokens.get('spacing', {}), indent=2)};
'''
        files.append({
            'path': 'tokens.js',
            'language': 'javascript',
            'content': tokens_content
        })

    return files


def generate_react_tailwind_component(name, comp_type, styles, props):
    """Generate React component with Tailwind CSS"""
    tailwind_classes = generate_tailwind_classes(styles)

    props_str = ', '.join([p.get('name', 'prop') for p in props]) if props else ''
    props_destructure = f"{{ {props_str} }}" if props_str else ''

    # Component template based on type
    if comp_type == 'button':
        inner_content = '{children}'
        props_destructure = '{ children, onClick, ...props }'
        return f'''import React from 'react';

const {name} = ({props_destructure}) => {{
  return (
    <button
      className="{tailwind_classes} cursor-pointer hover:opacity-90 transition-opacity"
      onClick={{onClick}}
      {{...props}}
    >
      {inner_content}
    </button>
  );
}};

export default {name};
'''
    elif comp_type == 'input':
        return f'''import React from 'react';

const {name} = ({{ value, onChange, placeholder, ...props }}) => {{
  return (
    <input
      className="{tailwind_classes} outline-none focus:ring-2 focus:ring-blue-500"
      value={{value}}
      onChange={{onChange}}
      placeholder={{placeholder}}
      {{...props}}
    />
  );
}};

export default {name};
'''
    elif comp_type == 'card':
        return f'''import React from 'react';

const {name} = ({{ children, ...props }}) => {{
  return (
    <div className="{tailwind_classes} shadow-lg" {{...props}}>
      {{children}}
    </div>
  );
}};

export default {name};
'''
    else:
        return f'''import React from 'react';

const {name} = ({props_destructure or '{ children }'}) => {{
  return (
    <div className="{tailwind_classes}">
      {{children}}
    </div>
  );
}};

export default {name};
'''


def generate_react_styled_component(name, comp_type, styles, props):
    """Generate React component with styled-components"""
    css_props = []

    for key, value in (styles or {}).items():
        css_key = ''.join(['-' + c.lower() if c.isupper() else c for c in key]).lstrip('-')
        if isinstance(value, dict):
            continue
        if isinstance(value, (int, float)) and key not in ['opacity', 'fontWeight']:
            value = f"{value}px"
        css_props.append(f"  {css_key}: {value};")

    styled_css = '\n'.join(css_props) if css_props else '  /* Add styles */'

    return f'''import React from 'react';
import styled from 'styled-components';

const Styled{name} = styled.div`
{styled_css}
`;

const {name} = ({{ children, ...props }}) => {{
  return (
    <Styled{name} {{...props}}>
      {{children}}
    </Styled{name}>
  );
}};

export default {name};
'''


def generate_react_css_component(name, comp_type, styles, props):
    """Generate React component with CSS modules"""
    class_name = name.lower()

    return f'''import React from 'react';
import './App.css';

const {name} = ({{ children, ...props }}) => {{
  return (
    <div className="{class_name}" {{...props}}>
      {{children}}
    </div>
  );
}};

export default {name};
'''


# =============================================================================
# VUE CODE GENERATOR
# =============================================================================

def generate_vue_code(parse_id, styling='tailwind', components=None, options=None):
    """Generate Vue components from parsed Figma design"""
    options = options or {}
    files = []

    design = get_parsed_design(parse_id)
    if not design:
        return files

    mappings = get_component_mappings(parse_id)
    design_tokens = design.get('design_tokens') or {}

    # Filter components if specified
    if components:
        mappings = [m for m in mappings if m['figma_node_id'] in components]

    component_names = []

    for mapping in mappings:
        comp_name = mapping.get('suggested_component_name', 'Component')
        comp_name = ''.join(word.capitalize() for word in comp_name.replace('-', '_').split('_'))
        comp_type = mapping.get('component_type', 'div')
        styles = mapping.get('styles') or {}
        props = mapping.get('props') or []

        component_names.append(comp_name)

        # Generate Vue SFC
        if styling == 'tailwind':
            vue_content = generate_vue_tailwind_component(comp_name, comp_type, styles, props)
        else:
            vue_content = generate_vue_scoped_component(comp_name, comp_type, styles, props)

        files.append({
            'path': f"components/{comp_name}.vue",
            'language': 'vue',
            'content': vue_content
        })

    # Generate App.vue
    imports = '\n'.join([f"import {name} from './components/{name}.vue';" for name in component_names])
    component_tags = '\n      '.join([f"<{name} />" for name in component_names])
    components_obj = ', '.join(component_names)

    app_content = f'''<template>
  <div id="app">
    <main>
      {component_tags}
    </main>
  </div>
</template>

<script>
{imports}

export default {{
  name: 'App',
  components: {{
    {components_obj}
  }}
}}
</script>

<style>
#app {{
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}}
</style>
'''

    files.append({
        'path': 'App.vue',
        'language': 'vue',
        'content': app_content
    })

    return files


def generate_vue_tailwind_component(name, comp_type, styles, props):
    """Generate Vue SFC with Tailwind"""
    tailwind_classes = generate_tailwind_classes(styles)

    props_def = '\n    '.join([f"{p.get('name', 'prop')}: {{ type: String, default: '' }}," for p in props]) if props else ''

    if comp_type == 'button':
        return f'''<template>
  <button
    class="{tailwind_classes} cursor-pointer hover:opacity-90 transition-opacity"
    @click="$emit('click')"
  >
    <slot />
  </button>
</template>

<script>
export default {{
  name: '{name}',
  emits: ['click']
}}
</script>
'''
    else:
        return f'''<template>
  <div class="{tailwind_classes}">
    <slot />
  </div>
</template>

<script>
export default {{
  name: '{name}',
  props: {{
    {props_def}
  }}
}}
</script>
'''


def generate_vue_scoped_component(name, comp_type, styles, props):
    """Generate Vue SFC with scoped CSS"""
    css_props = []

    for key, value in (styles or {}).items():
        css_key = ''.join(['-' + c.lower() if c.isupper() else c for c in key]).lstrip('-')
        if isinstance(value, dict):
            continue
        if isinstance(value, (int, float)) and key not in ['opacity', 'fontWeight']:
            value = f"{value}px"
        css_props.append(f"  {css_key}: {value};")

    scoped_css = '\n'.join(css_props) if css_props else '  /* Add styles */'

    return f'''<template>
  <div class="{name.lower()}">
    <slot />
  </div>
</template>

<script>
export default {{
  name: '{name}'
}}
</script>

<style scoped>
.{name.lower()} {{
{scoped_css}
}}
</style>
'''


# =============================================================================
# HTML CODE GENERATOR
# =============================================================================

def generate_html_code(parse_id, styling='tailwind', components=None, options=None):
    """Generate HTML/CSS from parsed Figma design"""
    options = options or {}
    files = []

    design = get_parsed_design(parse_id)
    if not design:
        return files

    mappings = get_component_mappings(parse_id)
    design_tokens = design.get('design_tokens') or {}
    file_name = design.get('figma_file_name', 'design')

    # Filter components if specified
    if components:
        mappings = [m for m in mappings if m['figma_node_id'] in components]

    # Build HTML sections
    html_sections = []
    css_rules = []

    for mapping in mappings:
        comp_name = mapping.get('suggested_component_name', 'component')
        comp_type = mapping.get('component_type', 'div')
        styles = mapping.get('styles') or {}

        class_name = comp_name.lower().replace(' ', '-')

        if styling == 'tailwind':
            tailwind_classes = generate_tailwind_classes(styles)
            html_sections.append(f'''    <div class="{tailwind_classes}">
      <!-- {comp_name} content -->
    </div>''')
        else:
            html_sections.append(f'''    <div class="{class_name}">
      <!-- {comp_name} content -->
    </div>''')
            css_rules.append(generate_css_styles(styles, class_name))

    # Generate index.html
    tailwind_cdn = '<script src="https://cdn.tailwindcss.com"></script>' if styling == 'tailwind' else ''
    css_link = '<link rel="stylesheet" href="styles.css">' if styling != 'tailwind' else ''

    html_content = f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{file_name}</title>
  {tailwind_cdn}
  {css_link}
</head>
<body class="{"min-h-screen bg-gray-50" if styling == "tailwind" else ""}">
  <main>
{chr(10).join(html_sections)}
  </main>
</body>
</html>
'''

    files.append({
        'path': 'index.html',
        'language': 'html',
        'content': html_content
    })

    # Generate CSS file if not using Tailwind
    if styling != 'tailwind' and css_rules:
        css_content = f'''/* Generated from Figma - {file_name} */

* {{
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}}

body {{
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  min-height: 100vh;
  background-color: #f9fafb;
}}

{chr(10).join(css_rules)}
'''
        files.append({
            'path': 'styles.css',
            'language': 'css',
            'content': css_content
        })

    return files
