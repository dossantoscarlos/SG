# SG Gestão

Painel administrativo completo para pequenos negócios, feito em Python com
Streamlit. Reúne visão geral, pedidos, logística, catálogo, clientes e relatórios
em uma interface responsiva, em português e com dados de demonstração prontos
para uso. Versão atual: **v1.5**.

## Recursos

- **Login administrativo** com senha protegida por scrypt, bloqueio temporário
  após tentativas inválidas e sessão de 12 horas.
- **Controle de acesso no estilo Django**, com perfis (grupos), permissões por
  recurso e ação, concessões diretas e superusuário com acesso total.
- **Visão geral** com receita, pedidos, ticket médio, novos clientes, gráficos,
  produtos em destaque e alertas de estoque.
- **Pedidos** com criação em janela modal, carrinho, desconto, frete, controle
  automático de estoque, atualização de status e exclusão.
- **Logística** com fila de expedição, cadastro de transportadoras, código e link
  de rastreio, previsão de entrega, registro de entrega, indicadores de prazo e
  desempenho por transportadora.
- **Movimentações de estoque** em documentos com cabeçalho e vários itens.
  Cada documento tem origem, destino, motivo, responsável, custo, status, nota
  fiscal e histórico de alterações. Entradas e transferências podem ficar em
  trânsito, com recebimento total, parcial ou com divergência.
- **Estorno auditável**: documentos manuais concluídos ou recebidos podem ser
  estornados por um documento inverso, mantendo o histórico original intacto.
  Vendas e reativações de pedidos são corrigidas pelo cancelamento do pedido.
- **Produtos** com cadastro, edição, ativação, exclusão, preço, custo, estoque e
  estoque mínimo, com registro dos ajustes no livro-razão de estoque. Produtos
  com pedidos ou histórico de movimentação são desativados, não excluídos.
- **Clientes** com ficha completa, histórico de compras, receita, ticket médio,
  situação e observações de atendimento. Quem tem permissão de alteração pode
  editar nome, e-mail, telefone, localização e situação diretamente pela célula,
  usando a edição rápida.
- **Relatórios** por período (7, 30, 90 dias, ano atual ou intervalo
  personalizado) com receita, lucro bruto estimado, categorias, produtos,
  clientes, pagamentos e detalhamento de pedidos e itens.
- **Exportação** do relatório em Excel (várias abas) e CSV.
- **Acessos** para criar contas, atribuir vários perfis, conceder permissões
  diretas e montar perfis com uma matriz de permissões por módulo.
- **Configurações** de perfil e senha, além de informações da conta e do sistema.
- **Interface responsiva** para computador, tablet e celular, com tema escuro,
  contraste alto e navegação lateral agrupada por seções (Operação, Cadastros,
  Análise e Administração).

## Tecnologias

| Camada | Tecnologia |
| --- | --- |
| Interface | Streamlit 1.66 |
| Dados | SQLite |
| Tabelas e análise | pandas |
| Gráficos | Altair |
| Exportação | openpyxl |

## Requisitos

- Python 3.11 ou superior
- pip

## Como executar

### Windows (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run streamlit_app.py
```

### Linux ou macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

O painel abre em `http://localhost:8501`.

### Credenciais de demonstração

```text
E-mail: admin@sg.com.br
Senha:  admin123
```

No primeiro acesso, o painel avisa que a senha é inicial. Altere-a em
**Configurações → Senha de acesso**. O aviso desaparece automaticamente após a
troca. Para ocultar as credenciais na tela de login, defina
`SG_SHOW_DEMO_HINT=0` antes de iniciar a aplicação.

## Perfis e permissões

O controle de acesso segue o mesmo modelo de grupos e permissões do Django:

- cada permissão tem um codename no formato `app.acao_recurso`, como
  `orders.add_order`, `products.change_product` ou `auth.delete_user`;
- são 29 permissões em 7 módulos: Visão geral, Pedidos, Logística, Produtos,
  Clientes, Relatórios e Acessos;
- **perfis** funcionam como os grupos do Django e reúnem permissões;
- um usuário pode ter **vários perfis** e também **permissões diretas**;
- um **superusuário** ignora a verificação e tem acesso total;
- contas inativas não entram no painel, mesmo que tenham permissões.

A página **Acessos** é exibida apenas para quem possui permissão de ver usuários
ou perfis. Nela é possível criar contas, definir senha inicial, atribuir perfis,
conceder permissões diretas e editar a matriz de permissões de cada perfil. A
página **Configurações** continua acessível a qualquer conta autenticada para
trocar a própria senha.

### Perfis padrão

| Perfil | Acesso |
| --- | --- |
| Administradores | Todas as 29 permissões, incluindo a gestão de acessos. Perfil protegido pelo sistema. |
| Gerentes | Vendas, catálogo, logística, clientes e relatórios, sem gerenciar contas e perfis. |
| Vendas | Visão geral, pedidos (ver, criar e alterar status), logística (ver e gerenciar envios), produtos (ver) e clientes (ver, criar e editar). |
| Consulta | Somente leitura de visão geral, pedidos, logística, produtos, clientes e relatórios. |

O administrador criado no primeiro uso é superusuário e pertence ao perfil
**Administradores**. O sistema impede excluir ou desativar a própria conta,
remover o próprio superusuário, excluir perfis em uso e ficar sem pelo menos um
superusuário ativo. Em bancos existentes, as permissões **Logística** são
adicionadas automaticamente apenas ao perfil **Administradores**; conceda-as aos
demais perfis em **Acessos → Perfis** quando necessário.

### Atualização de bancos existentes

Na primeira execução desta versão, o banco é migrado automaticamente para a
versão 5 do esquema. A migração é idempotente e:

- cria as tabelas `stock_documents`, `stock_document_items`, `stock_transits` e
  `stock_status_history`;
- converte as movimentações antigas em documentos equivalentes, agrupando
  movimentos do mesmo pedido, tipo e horário em um único documento;
- preserva o livro-razão existente, com documento, item, saldo anterior e
  posterior, custo, entidade, nota fiscal e histórico de status;
- mantém o saldo central em `products.stock` e cria a visão separada de itens em
  trânsito para entradas e transferências ainda não recebidas;
- preserva transportadoras, envios, notas fiscais e cadastros já existentes.

Pedidos, clientes, produtos e valores não são recriados. Usuários que já existiam
recebem o perfil **Administradores** para preservar o acesso anterior, e quem
tinha o papel antigo `Administrador` passa a ser superusuário. Faça uma cópia de
`data/sg.db` antes de atualizar uma instalação em uso.

## Estrutura do projeto

```text
SG/
├── .streamlit/
│   └── config.toml          # Tema, fontes e cores
├── app_pages/
│   ├── access.py             # Usuários, perfis e permissões
│   ├── dashboard.py          # Visão geral
│   ├── login.py              # Tela de entrada
│   ├── logistics.py          # Expedição, transportadoras, entidades e estoque
│   ├── orders.py             # Gestão de pedidos
│   ├── products.py           # Catálogo de produtos
│   ├── customers.py          # Cadastro e ficha de clientes
│   ├── reports.py            # Relatórios e exportações
│   └── settings.py           # Perfil, senha e sistema
├── assets/                  # Logos e favicon em SVG
├── data/
│   └── sg.db                # Banco SQLite (criado automaticamente)
├── lib/
│   ├── acl.py               # Perfis, permissões e regras de acesso
│   ├── analytics.py         # Consultas do painel e dos relatórios
│   ├── auth.py              # Autenticação e conta
│   ├── catalog.py           # Produtos e clientes
│   ├── charts.py            # Gráficos Altair
│   ├── database.py          # Esquema, conexão e dados demo
│   ├── errors.py            # Erro de domínio
│   ├── inventory.py         # Documentos, livro-razão, trânsito, estorno e notas
│   ├── invoices.py          # Leitura segura de XML de NF-e
│   ├── logistics.py         # Envios, transportadoras, prazos e indicadores
│   ├── order_ui.py          # Janela de novo pedido
│   ├── orders.py            # Regras de pedidos e estoque
│   ├── reports.py           # Geração de Excel e CSV
│   ├── security.py          # Hash de senha e força da senha
│   ├── stock_items.py        # Tabela de itens do documento de estoque
│   └── ui.py                # Formatadores e componentes visuais
├── requirements.txt
├── streamlit_app.py          # Entrada, sessão e navegação
└── README.md
```

## Dados de demonstração

Na primeira execução, o banco `data/sg.db` é criado e populado com 21 produtos,
19 clientes e 118 pedidos distribuídos nos últimos meses. Os pedidos usam datas
relativas ao dia atual, então os indicadores permanecem realistas. As entidades
de estoque começam vazias: cadastre filiais e fornecedores em **Logística →
Entidades**; clientes já ficam disponíveis a partir da página **Clientes**.

O seed só ocorre quando a tabela de produtos está vazia. Para recriar o banco de
demonstração do zero:

```powershell
.\.venv\Scripts\python.exe -c "from lib.database import reset_demo_database; reset_demo_database()"
```

> Atenção: esse comando apaga o banco atual e todos os dados cadastrados.

Para iniciar com um banco vazio, sem dados de demonstração:

```powershell
$env:SG_SEED_DEMO = "0"
streamlit run streamlit_app.py
```

## Fluxo logístico

- Pedidos com status **Pago** entram na fila **A separar**.
- Em **Logística → Expedição**, selecione o pedido e use **Preparar envio** para
  informar transportadora, serviço, código de rastreio, previsão de entrega e
  frete. A opção **Despachar agora** muda o pedido para **Enviado**.
- Pedidos **Enviados** aparecem como **Em trânsito** ou **Atrasados** quando a
  previsão vence. Use **Marcar entregue** para registrar a data e concluir o
  pedido como **Entregue**.
- O link de rastreio é montado a partir do endereço da transportadora. Use o
  marcador `{tracking}` no endereço, por exemplo
  `https://transportadora.com/rastreio?codigo={tracking}`.
- Transportadoras não são excluídas para preservar o histórico; elas podem ser
  desativadas.
- A aba **Estoque** mostra o livro-razão imutável: documento, produto, status,
  quantidade, saldo anterior e posterior, custo, entidade e nota fiscal. O saldo
  central continua em `products.stock`.
- A aba **Documentos** cria **Entrada**, **Saída** e **Transferência** com
  cabeçalho e vários itens. O documento registra motivo, responsável, origem,
  destino, custo unitário, custo total, nota fiscal e histórico de status.
- Entradas concluídas somam ao saldo imediatamente. Entradas em trânsito só
  somam quando o recebimento é confirmado. Saídas baixam o saldo na criação;
  transferências **A separar** baixam no **Despachar**, quando passam a
  **Em trânsito**. O trânsito é uma visão separada, sem saldo por filial.
- O recebimento pode ser total, parcial ou encerrado com **Divergência** quando
  chega menos do que o previsto. Itens em trânsito aparecem em uma seção própria
  e também no detalhe do documento.
- Documentos manuais concluídos ou recebidos podem ser **estornados** por um
  documento inverso. O original nunca é editado nem excluído; o histórico e o
  vínculo entre original e estorno permanecem visíveis. Documentos de pedido são
  corrigidos pelo cancelamento do pedido, não pelo estorno.
- Pedidos geram documentos automaticamente: venda (**A separar**), cancelamento,
  reativação e exclusão. O status do documento de venda acompanha o envio e a
  entrega do pedido.
- O campo **XML da nota fiscal (opcional)** aceita uma NF-e de até 5 MB: o
  sistema valida o arquivo, extrai os dados principais, guarda o XML original e
  reutiliza a nota quando a chave de acesso já foi importada. O XML pode ser
  baixado no detalhe do documento e em **Notas fiscais importadas**.
- A aba **Entidades** cadastra filiais e fornecedores usados como origem ou
  destino do estoque. Clientes são cadastrados na página **Clientes** e também
  ficam disponíveis para movimentações manuais. Entidades não são excluídas para
  preservar o histórico; elas podem ser desativadas.
- As ações dependem das permissões `logistics.view_shipment`,
  `logistics.change_shipment`, `logistics.manage_carrier`,
  `logistics.adjust_stock`, `logistics.receive_stock` e
  `logistics.reverse_stock`. A permissão `logistics.adjust_stock` também gerencia
  as entidades de estoque.

## Configurações por variável de ambiente

| Variável | Padrão | Descrição |
| --- | --- | --- |
| `SG_ADMIN_NAME` | `Administrador` | Nome do administrador criado no primeiro uso. |
| `SG_ADMIN_EMAIL` | `admin@sg.com.br` | E-mail do administrador inicial. |
| `SG_ADMIN_PASSWORD` | `admin123` | Senha inicial. Se definida, o usuário não recebe o aviso de senha padrão. |
| `SG_SEED_DEMO` | `1` | Use `0` para não popular dados de demonstração. |
| `SG_SHOW_DEMO_HINT` | `1` | Use `0` para ocultar as credenciais na tela de login. |
| `SG_DB_PATH` | `data/sg.db` | Caminho alternativo para o arquivo SQLite. |

Defina as variáveis **antes** da primeira execução, pois o administrador só é
criado quando a tabela de usuários está vazia. O administrador inicial recebe
automaticamente o perfil **Administradores** e o nível de superusuário.

Exemplo no PowerShell:

```powershell
$env:SG_ADMIN_EMAIL = "gestor@minhaempresa.com"
$env:SG_ADMIN_PASSWORD = "uma-senha-forte-123"
$env:SG_SHOW_DEMO_HINT = "0"
$env:SG_SEED_DEMO = "0"
streamlit run streamlit_app.py
```

## Personalização

- **Cores, fontes e espaçamentos:** edite `.streamlit/config.toml`. O painel
  oferece os modos claro e escuro nas seções `[theme.light]` e `[theme.dark]`.
  O escuro usa o teal `#0F766E` como cor principal, fundos azul-marinho e uma
  barra lateral ainda mais escura; o claro usa a paleta clara anterior. A barra
  lateral permanece escura nos dois modos. Para alternar rapidamente, use o
  botão **Tema claro**/**Tema escuro** na barra lateral. O menu **⋮** no canto
  superior direito também oferece **System**, **Light** e **Dark**. A preferência
  fica salva no navegador; na primeira visita, o Streamlit segue o tema do
  sistema.
- **Logos:** substitua os arquivos em `assets/` mantendo os nomes, ou ajuste os
  caminhos em `streamlit_app.py`. O login usa `logo_login.svg` no modo escuro e
  `logo_login_light.svg` no modo claro.
- **Categorias e formas de pagamento:** edite as constantes em
  `lib/database.py` (`CATEGORIES`, `PAYMENT_METHODS`, `CHANNELS`).
- **Texto e identidade:** a marca “SG Gestão” aparece no título, na sidebar e nos
  arquivos SVG.

## Segurança e implantação

- As senhas nunca são salvas em texto puro: o hash scrypt inclui salt aleatório
  e parâmetros de custo.
- Após cinco tentativas inválidas, o login fica bloqueado por 30 segundos.
- A sessão expira após 12 horas e pode ser encerrada pelo botão **Sair**.
- O logout limpa a sessão e retorna à tela de login, sem manter a navegação
  ou a sidebar administrativa.
- O acesso é verificado no servidor: páginas, botões e ações são bloqueados
  conforme as permissões efetivas do usuário, e não apenas ocultados na interface.
- Apenas superusuários podem conceder ou remover o nível de superusuário e
  alterar contas de superusuário. O sistema exige pelo menos um superusuário
  ativo.
- O banco SQLite é local e não deve ser versionado. A pasta `data/` e os arquivos
  `*.db`, `*.db-wal` e `*.db-shm` já estão no `.gitignore`.
- Para uso em produção, sirva a aplicação atrás de HTTPS, mantenha o arquivo do
  banco em um disco persistente e faça backups regulares.
- A importação de XML de NF-e aceita arquivos de até 5 MB, rejeita declarações
  de DTD/entidades e preserva o XML original no banco local. O arquivo não é
  executado nem enviado para serviços externos.
- O SQLite atende bem a um único processo/servidor. Para vários usuários
  simultâneos em grande volume, considere migrar para PostgreSQL.
- Nunca versione `.streamlit/secrets.toml` nem exponha o banco publicamente.

Exemplo de execução em uma porta específica:

```powershell
streamlit run streamlit_app.py --server.port 8501 --server.address 0.0.0.0
```

## Validação rápida

```powershell
.\.venv\Scripts\python.exe -m compileall .
```

Depois, abra o painel e confira o login, a navegação, a criação de um pedido, a
edição de um produto, os filtros de clientes, a exportação de um relatório e a
criação de um usuário com um perfil restrito em **Acessos**. Em **Logística**,
teste preparar um envio para um pedido pago, abrir o rastreio, registrar a
entrega, editar uma transportadora, cadastrar uma filial ou fornecedor em
**Entidades** e criar um documento com dois itens em **Documentos**. Confira o
livro-razão em **Estoque**, o detalhe do documento, o histórico de status e a
exportação CSV. Para testar o trânsito, crie uma entrada em trânsito ou uma
transferência **A separar**, use **Despachar** e depois **Receber**; confirme o
recebimento parcial ou com divergência e o estorno do documento. Confira também
a rejeição de um XML inválido e a reutilização de uma nota pela chave de acesso.
