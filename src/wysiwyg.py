import os
import streamlit.components.v1 as components

# Get the path to the HTML source directory
_parent_dir = os.path.dirname(os.path.abspath(__file__))
_build_dir = os.path.join(_parent_dir, "wysiwyg_component")

# Declare the component
_component_func = components.declare_component(
    "cv_wysiwyg",
    path=_build_dir
)

def cv_wysiwyg(cv_data, key=None):
    """
    Render the WYSIWYG CV editor component in Streamlit.
    
    Args:
        cv_data (dict): JSON CV structure.
        key (str): Streamlit unique key.
        
    Returns:
        dict: The updated CV JSON data.
    """
    return _component_func(cv_data=cv_data, key=key, default=cv_data)
