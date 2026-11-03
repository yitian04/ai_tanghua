import tempfile
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from src.core.preferences import PreferenceStore


class ParameterUITests(unittest.TestCase):
    def test_remembered_values_and_restore_have_single_state_source(self):
        with tempfile.TemporaryDirectory() as root:
            store=PreferenceStore(root)
            store.remember('planning',{'Model':'B','Speed':12.0,'Enabled':True,'Caption':'saved','Range':[2.0,4.0]})
            code=f"""
from apps.gui.parameter_ui import ui as st,parameter_scope,render_current_actions
with parameter_scope({root!r},'planning'):
    st.selectbox('Model',['A','B'],index=1,key='model_source_stage_1')
    st.number_input('Speed',min_value=0.0,value=3.0,key='speed')
    st.checkbox('Enabled',value=True,key='enabled')
    st.text_input('Caption',value='initial',key='caption')
    st.slider('Range',min_value=0.0,max_value=10.0,value=(1.0,5.0),key='range')
    render_current_actions()
"""
            from streamlit.elements.lib import policies
            with patch.object(policies,'_shown_default_value_warning',False),patch.object(policies._LOGGER,'warning') as warning:
                app=AppTest.from_string(code).run()
                self.assertFalse(app.exception)
                self.assertEqual(app.selectbox[0].value,'B')
                self.assertEqual(app.number_input[0].value,12.0)
                self.assertEqual(app.slider[0].value,(2.0,4.0))
                app.selectbox[0].select('A').run()
                self.assertFalse(app.exception)
                self.assertEqual(app.slider[0].value,(2.0,4.0))
                app.button[0].click().run()
                self.assertFalse(app.exception)
                self.assertEqual(app.number_input[0].value,3.0)
                self.assertEqual(app.selectbox[0].value,'B')
                warning.assert_not_called()

    def test_removed_widget_callback_is_ignored_without_reviving_stale_state(self):
        from types import SimpleNamespace
        from apps.gui import parameter_ui
        class Target:
            def radio(self,label,options,index=0,key=None,on_change=None,args=None,kwargs=None):
                self.callback=on_change
                return options[index]
        with tempfile.TemporaryDirectory() as root:
            target=Target();session={};calls=[]
            key='ai_sugar_prompt_language'
            with patch.object(parameter_ui,'_st',SimpleNamespace(session_state=session)):
                with parameter_ui.parameter_scope(root,'ai'):
                    parameter_ui.UI(target).radio('提示词语言',['zh','en'],key=key,on_change=lambda: calls.append('changed'))
                session[key]='en';target.callback()
                self.assertEqual(PreferenceStore(root).current('ai')[key],'en')
                self.assertEqual(calls,['changed'])
                del session[key]
                target.callback()
                self.assertNotIn(key,session)
                self.assertEqual(PreferenceStore(root).current('ai')[key],'en')
                self.assertEqual(calls,['changed'])
