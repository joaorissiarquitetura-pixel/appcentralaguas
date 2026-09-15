# Diagnóstico técnico do backend Central Águas

Data da análise: 2026-09-11

## Escopo

Este diagnóstico corresponde às Fases 1 e 2 solicitadas: auditar o projeto atual e registrar o estado técnico antes de qualquer refatoração maior.

O objetivo é evoluir o backend sem reescrever o sistema do zero, sem quebrar o site atual e sem alterar o banco de forma destrutiva.

## Legenda

- ✅ Já existe e está adequado
- 🟡 Existe, mas precisa ser melhorado
- 🔴 Não existe
- 🔵 Já está preparado para ser utilizado pelo App

## Stack e estrutura atual

Status: 🟡 Existe, mas precisa ser melhorado

O sistema principal em uso está em `app/`, usando FastAPI, Jinja2, SQLAlchemy e sessões via cookie.

Arquivos centrais identificados:

- `app/main.py`: inicialização FastAPI, middlewares, rotas e startup.
- `app/models.py`: models SQLAlchemy principais.
- `app/database.py`: engine e sessão SQLAlchemy.
- `app/config.py`: variáveis de ambiente e validações básicas.
- `app/routers/`: rotas públicas, cliente, atendente, admin e APIs do app.
- `app/services/`: regras auxiliares já separadas em alguns serviços.
- `app/templates/`: telas Jinja do site, app/PWA e painel.
- `tests/`: testes smoke e testes do catálogo GRJ.

Também existe uma pasta `backend/` com estrutura de apps, mas sem arquivos Python relevantes encontrados na auditoria. Ela parece ser um esqueleto antigo ou incompleto, não o backend efetivo em produção.

## Diagnóstico por área

| Área | Status | Diagnóstico |
| --- | --- | --- |
| Arquitetura backend | 🟡 | Há separação parcial por routers e services, mas ainda existem regras de negócio em controllers/templates, principalmente em `public.py` e `admin.py`. |
| Site atual | ✅ | O site/app público existe e está integrado ao FastAPI/Jinja. Deve ser preservado. |
| Painel administrativo | 🟡 | Existe painel admin com clientes, mapa, alertas, loja, cupons e backend do app. Precisa evoluir permissões, auditoria e organização. |
| App/PWA | 🔵 | `/app`, manifest, service worker, push subscription, FCM token e localização já estão preparados. |
| Android/APK | 🔵 | Projeto Android existe, Firebase configurado, ícones gerados e URL inicial ajustada para `https://app.centralaguas.com.br/app`. |
| API versionada | 🔴 | Existem APIs pontuais, mas não há `/api/v1/` organizada por domínio. |
| Autenticação | 🟡 | Existe login por sessão para cliente e atendente/admin. Falta centralização completa, tokens/API auth, renovação e proteção contra brute force. |
| Senhas | ✅ | Hash com Passlib/bcrypt está implementado. |
| Usuários internos | 🟡 | `Attendant` possui `role` simples. Falta modelagem de usuários/perfis/permissões granulares. |
| Clientes | 🟡 | `Customer` existe com dados pessoais, telefone, endereço, indicação, consumo e pontos. Precisa separar endereços e melhorar validação/soft delete. |
| Endereços | 🟡 | Endereço está embutido no cliente. Há CEP/geocoding. Falta tabela própria para múltiplos endereços. |
| Produtos | 🟡 | `Product` existe com nome, descrição, preços, promo, imagem, status e ativo. Faltam categoria, marca, SKU, capacidade, unidade, retornável, estoque mínimo e estoque real. |
| Categorias | 🔴 | Não há entidade própria de categoria. Há classificação por texto no código público. |
| Estoque | 🔴 | Não há motor real de estoque com movimentações, reservado/disponível/físico e histórico. |
| Pedidos | 🔴 | Não há entidade `Order`/`OrderItem` própria. Existem transações de fidelidade e checkout público, mas não motor de pedidos completo. |
| Itens do pedido | 🔴 | `TransactionItem` existe para lançamento de fidelidade, não para pedido comercial completo. |
| Fidelidade | 🟡 | Pontos, transações, resgates e `LoyaltyLedger` existem. Precisa registrar saldo anterior/posterior e origem mais padronizada. |
| Pagamentos | 🔴 | Não há `PaymentService` nem entidade de pagamento independente. |
| Entregas | 🔴 | Não há módulo de entregas com status, entregador e histórico. |
| Assinaturas | 🟡 | Há página/ponte de assinatura e integration service, mas não módulo interno completo. |
| Vasilhames | 🔴 | Não há estrutura específica para vasilhames retornáveis. |
| RBAC/permissões | 🔴 | Há `role` simples e `is_admin`. Falta RBAC granular com permissões. |
| Logs de auditoria | 🟡 | Existe `app/services/audit.py`, mas não foi identificada tabela/model central de auditoria cobrindo ações críticas. |
| Logs técnicos | 🟡 | Há logging básico em `main.py` e services. Falta padronização estruturada e política de mascaramento. |
| Notificações | 🔵 | Existe `AppNotification`, `PushSubscription`, `AppDevice`, Web Push e Firebase FCM preparados. Falta fila/job, leitura, canais e histórico por destinatário. |
| Integrações | 🟡 | Existem integrações GRJ, WhatsApp, geocoding, Firebase/push. Falta camada formal `integrations/` com adapters. |
| API do app | 🔵 | `/api/app/bootstrap`, `/device`, `/push-subscription`, `/fcm-token`, `/location/check` existem. Devem ser evoluídas para `/api/v1/`. |
| Documentação API | 🟡 | FastAPI gera Swagger padrão, mas não há documentação própria de contratos e autenticação. |
| Segurança | 🟡 | Existem validações de secret, env e hash de senha. Faltam CSRF nos forms, rate limiting, headers, CORS explícito, upload mais robusto e RBAC. |
| Backups | 🔴 | Não há rotina documentada de backup/restore do banco de produção. |
| Migrations | 🟡 | Há `schema_updates.py` com alterações runtime seguras, mas não há Alembic/migration versionada. |
| Transações críticas | 🟡 | SQLAlchemy session é usada, mas regras críticas de estoque/pedido/pagamento ainda não existem. |
| Idempotência | 🔴 | Não há infraestrutura de idempotência para pedidos, pagamentos ou webhooks. |
| Webhooks | 🔴 | Não há estrutura genérica `/api/v1/webhooks/`. |
| Health check | 🔴 | Não foi identificado endpoint `/health` dedicado. |
| Testes | 🟡 | Existem testes smoke e catálogo GRJ. Falta cobertura de autenticação, permissões, estoque, pedidos, fidelidade e pagamentos. |
| Ambientes | 🟡 | Config por `.env` existe. Precisa separar melhor development/test/production e remover referências legadas/confusas. |
| README técnico | 🟡 | README existe, mas ainda é curto para arquitetura, migrations, jobs, API e operação. |

## Models atuais relevantes

### Já existentes

- `Customer`
- `PasswordResetToken`
- `Attendant`
- `Product`
- `Coupon`
- `AppDevice`
- `PushSubscription`
- `LocationAccessLog`
- `AppNotification`
- `Transaction`
- `TransactionItem`
- `Redemption`
- `LoyaltyLedger`
- `Alert`

### Lacunas de modelagem

Entidades recomendadas para fases futuras, sem migração destrutiva:

- `Role`
- `Permission`
- `UserRole`
- `RolePermission`
- `CustomerAddress`
- `ProductCategory`
- `InventoryBalance`
- `InventoryMovement`
- `Order`
- `OrderItem`
- `OrderStatusHistory`
- `Payment`
- `Delivery`
- `DeliveryStatusHistory`
- `ReturnableContainerBalance`
- `ReturnableContainerMovement`
- `AuditLog`
- `WebhookEvent`
- `IdempotencyKey`
- `NotificationRecipient`
- `JobRun`
- `SystemEvent`

## Rotas atuais

### Público/site

Status: ✅ / 🟡

Rotas em `app/routers/public.py`:

- `/`
- `/app`
- `/loja`
- `/fidelidade`
- `/assine`
- `/login`
- `/logout`
- `/cadastrar`
- `/api/cep/{cep}`
- `/api/localizacao/reversa`
- `/api/grj/produtos`
- `/api/grj/diagnostico`

Observação: `public.py` está grande e concentra muitas responsabilidades. Deve ser dividido gradualmente.

### Cliente

Status: 🟡

Rotas em `app/routers/customer.py`:

- `/meu-cartao`
- `/cliente`
- `/meu-cartao/data-nascimento`
- `/qr`

### Atendente

Status: 🟡

Rotas em `app/routers/attendant.py`:

- `/atendente/login`
- `/atendente/logout`
- `/atendente/lancar`
- `/atendente/resgatar`

Atende fidelidade operacional, mas ainda não é um app de funcionários completo.

### Admin

Status: 🟡 / 🔵

Rotas em `app/routers/admin.py`:

- `/admin`
- `/admin/customers`
- `/admin/map`
- `/admin/alerts`
- `/admin/site`
- `/admin/app`
- `/admin/app/status`
- `/admin/coupons`
- `/admin/notifications/send`
- rotas de manutenção, produtos e clientes

O admin já opera parte do negócio, mas ainda mistura funções comerciais, técnicas e manutenção.

### API do app

Status: 🔵

Rotas em `app/routers/app_api.py`:

- `/api/app/bootstrap`
- `/api/app/device`
- `/api/app/push-subscription`
- `/api/app/fcm-token`
- `/api/app/location/check`

Boa base para o app, mas precisa versionamento e padrão de resposta.

## Services atuais

Status geral: 🟡

Services identificados:

- `account_recovery.py`
- `address.py`
- `admin_operations.py`
- `app_access.py`
- `audit.py`
- `customer_portal.py`
- `gotinha.py`
- `grj_catalog.py`
- `integration.py`
- `loyalty.py`
- `push.py`
- `qr.py`
- `whatsapp.py`

Ponto positivo: já existe separação de algumas regras.

Ponto de atenção: regras importantes ainda estão dentro de routers e templates. A evolução deve mover regras para services sem quebrar as rotas existentes.

## Riscos técnicos atuais

1. `public.py` e `admin.py` grandes demais, com alta chance de regressão em mudanças futuras.
2. Ausência de API versionada `/api/v1/`.
3. Falta de RBAC granular.
4. Falta de motor real de pedido/estoque/pagamento.
5. Fidelidade tem ledger, mas saldo anterior/posterior ainda não está explícito.
6. Migrações runtime em `schema_updates.py` são úteis agora, mas não substituem Alembic em produção.
7. Várias responsabilidades misturadas entre site, app, admin e operação.
8. Dependências incluem FastAPI e Django, mas o backend Django não parece ativo; isso pode confundir deploy/manutenção.
9. Falta endpoint `/health`.
10. Testes atuais são insuficientes para regras financeiras/estoque/pedidos.

## Arquitetura alvo incremental

Não refazer do zero. Evoluir nesta direção:

```text
Site / App / Painel / App funcionário
        ↓
API versionada /api/v1
        ↓
Services de negócio
        ↓
Models / Repositories
        ↓
Banco de dados
```

Estrutura sugerida para fases futuras:

```text
app/
  api/
    v1/
      auth.py
      customers.py
      products.py
      inventory.py
      orders.py
      loyalty.py
      payments.py
      deliveries.py
      notifications.py
      webhooks.py
  services/
    auth_service.py
    customer_service.py
    product_service.py
    inventory_service.py
    order_service.py
    payment_service.py
    delivery_service.py
    loyalty_service.py
    notification_service.py
    audit_service.py
    event_service.py
  repositories/
    customers.py
    products.py
    inventory.py
    orders.py
  schemas/
    common.py
    auth.py
    customers.py
    products.py
    orders.py
  integrations/
    firebase.py
    whatsapp.py
    grj.py
    maps.py
  jobs/
    scheduler.py
    notifications.py
    stock.py
  middleware/
    security_headers.py
    request_id.py
```

## Plano de execução recomendado

### Fase 3: definir arquitetura preservando o sistema atual

Status: próxima fase.

Criar estrutura vazia/compatível para:

- `app/api/v1/`
- `app/schemas/`
- `app/repositories/`
- `app/integrations/`
- `app/jobs/`
- `app/middleware/`

Não mover tudo imediatamente. Começar pelas novas funcionalidades.

### Fase 4: correções estruturais críticas

Prioridade:

1. Criar `/health`.
2. Padronizar resposta da API.
3. Adicionar segurança básica de headers.
4. Documentar envs críticas.
5. Iniciar audit log persistente.

### Fase 5: API versionada

Criar `/api/v1/` sem remover rotas antigas.

Primeiros endpoints:

- `/api/v1/auth/session`
- `/api/v1/customers/me`
- `/api/v1/products`
- `/api/v1/loyalty/me`
- `/api/v1/notifications/register-device`
- `/api/v1/app/bootstrap`

### Fase 6: Services e regras de negócio

Mover gradualmente regras para services:

- autenticação
- produtos/catálogo
- cupons
- notificações
- app access

### Fase 7: Estoque e pedidos

Criar sem quebrar `Transaction` atual:

- `Order`
- `OrderItem`
- `OrderStatusHistory`
- `InventoryBalance`
- `InventoryMovement`

Implementar reserva de estoque e transações.

### Fase 8: Fidelidade e vasilhames

Preservar `Customer.points`.

Evoluir `LoyaltyLedger` para conter:

- saldo anterior
- saldo posterior
- tipo
- origem
- usuário responsável

Criar módulo de vasilhames retornáveis.

### Fase 9: Pagamentos e entregas

Criar:

- `Payment`
- `PaymentService`
- `Delivery`
- `DeliveryService`

Sem integrar gateway real até a modelagem estar estável.

### Fase 10: Eventos, jobs e notificações

Criar eventos internos:

- `ORDER_CREATED`
- `ORDER_DELIVERED`
- `LOYALTY_EARNED`
- `STOCK_LOW`
- `PAYMENT_RECEIVED`

Criar jobs leves para notificações pendentes e estoque mínimo.

### Fase 11: Auditoria, logs e segurança

Criar `AuditLog` e registrar:

- alteração de preço
- estoque
- cancelamento de pedido
- ajuste de pontos
- alteração de usuário/permissão
- bloqueio/desbloqueio de dispositivo

### Fase 12: Swagger/documentação

Aproveitar FastAPI/OpenAPI e documentar `/api/v1/`.

### Fase 13: Testes

Prioridade:

1. autenticação
2. permissões
3. estoque
4. pedido
5. cancelamento
6. fidelidade
7. pagamentos

## Conclusão

O projeto já possui uma base útil e em funcionamento para site, fidelidade, cliente, painel, app/PWA e push. A decisão correta é evoluir incrementalmente, mantendo rotas existentes e criando uma API versionada em paralelo.

Não é recomendado trocar tudo para outro backend agora. O caminho mais seguro é fortalecer o FastAPI atual com módulos, services, migrations versionadas, RBAC, auditoria, pedidos, estoque e pagamentos.

## Próxima ação recomendada

Iniciar Fase 3 e Fase 4 com mudanças pequenas e seguras:

1. criar estrutura `app/api/v1`;
2. criar padrão de resposta API;
3. criar `/health`;
4. criar schemas Pydantic comuns;
5. criar base de audit log persistente;
6. adicionar testes mínimos dessas novas bases.

## Atualização da Fase 3/4 inicial

Status: iniciada.

Bases adicionadas sem remover rotas existentes:

- pacote `app/api/v1/`;
- router agregado `/api/v1`;
- endpoint versionado `/api/v1/health`;
- endpoint versionado `/api/v1/app/bootstrap`;
- endpoint raiz `/health` para monitoramento;
- pacote `app/schemas/`;
- helpers `api_success` e `api_error` com formato padronizado;
- pacote `app/middleware/`;
- middleware de headers básicos de segurança;
- model `AdminAuditLog`;
- criação segura da tabela `admin_audit_logs` pelo schema runtime;
- auditoria para ações de cupom, notificação, bloqueio de device e inscrição push;
- testes iniciais em `tests/test_backend_foundation.py`.

Observação: as rotas antigas foram preservadas. A API versionada nasce em paralelo para permitir migração gradual do App, site e painel.

## Atualização da Fase 5 inicial

Status: iniciada.

APIs versionadas adicionadas sem remover endpoints antigos:

- `GET /api/v1/auth/session`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/register`
- `POST /api/v1/auth/logout`
- `GET /api/v1/customers/me`
- `GET /api/v1/customers/me/loyalty`
- `GET /api/v1/products`

Services novos:

- `app/services/auth_service.py`
- `app/services/catalog_service.py`

Schemas novos:

- `app/schemas/auth.py`
- `app/schemas/customer.py`
- `app/schemas/product.py`

Observação: a API v1 ainda usa a sessão por cookie existente para manter compatibilidade com o sistema atual. Token/JWT deve ser avaliado em uma fase posterior, junto com RBAC granular.
