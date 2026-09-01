// admin_table.js — módulo JS do st.components.v2.component() da tabela de usuários do painel
// admin (admin.py::_render_users_table). Estático, sem interpolação Python (diferente do HTML,
// que é montado por linha em admin.py) — lê o e-mail de cada botão via data-email, então não
// precisa saber nada sobre os dados em si.
//
// component.parentElement (não document!) é a raiz certa pra buscar elementos: com
// isolate_styles=True (o padrão), o HTML do componente roda em Shadow DOM, e parentElement é o
// próprio ShadowRoot. document.querySelector(...) buscaria na página INTEIRA do Streamlit, não só
// aqui dentro — bug real encontrado num spike desta migração (pegou por engano o botão "Deploy"
// do próprio Streamlit antes de trocar pra parentElement).
export default function (component) {
    const { setTriggerValue, parentElement } = component;

    parentElement.querySelectorAll(".btn-approve").forEach((btn) => {
        btn.onclick = () => setTriggerValue("approve_" + btn.dataset.email, true);
    });

    parentElement.querySelectorAll(".btn-revoke").forEach((btn) => {
        btn.onclick = () => setTriggerValue("revoke_" + btn.dataset.email, true);
    });
}
