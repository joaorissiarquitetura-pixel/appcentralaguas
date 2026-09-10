# Central Águas App

Aplicação FastAPI/Jinja para pedidos, fidelidade, cadastro de cliente e Gotinha da Central Águas.

## Deploy no Coolify

Use o `Dockerfile` da raiz. A aplicação expõe a porta `8000` e inicia com:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Configure as variáveis de ambiente no Coolify. Não coloque segredos no GitHub.

Variáveis principais:

```env
APP_ENV=production
DEBUG=false
SESSION_COOKIE_SECURE=true
AUTO_CREATE_TABLES=false
DATABASE_URL=
SECRET_KEY=
CENTRAL_AGUAS_APP_TOKEN=cole-o-token-da-api-do-grj-no-coolify
CENTRAL_AGUAS_PRODUCTS_API_URL=https://grupogrj.com.br/api/v1/central-aguas/products
LOCAL_TZ=America/Sao_Paulo
BUSINESS_NAME=Central Águas
```

O token da API GRJ deve ficar apenas nas variáveis de ambiente do deploy. Não grave o token real em commit.

## Rodar localmente

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Testes

```bash
python -m unittest tests.test_smoke_routes tests.test_grj_catalog_api
```
