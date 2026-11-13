# EcoLock

Sistema de identificação e autenticação biométrica por reconhecimento facial.
Trabalho da APS de Ciência da Computação (5º/6º semestre, 2026/2), disciplina de PIVC.

## Como executar (Windows)

1. Instale o Python 3.10 a 3.12 e o XAMPP.
2. No painel do XAMPP, clique em **Start** no módulo **MySQL**.
3. Na pasta do projeto, crie o ambiente virtual e instale as dependências.
   O `dlib-bin` é o dlib já compilado, então não é preciso instalar o Visual Studio.

   ```bash
   python -m venv .venv
   .venv/Scripts/python -m pip install opencv-python numpy Pillow mysql-connector-python customtkinter "setuptools<81" dlib-bin
   .venv/Scripts/python -m pip install face_recognition --no-deps
   .venv/Scripts/python -m pip install face_recognition_models Click
   ```

4. Execute:

   ```bash
   .venv/Scripts/python main.py
   ```

Na primeira execução, o banco `ecolock` e as tabelas são criados sozinhos a partir do `schema.sql`.

## Arquivos

| Arquivo | O que faz |
|---|---|
| `main.py` | Ponto de entrada e verificação da conexão com o banco |
| `config.py` | Parâmetros ajustáveis (tolerância, prova de vida, alertas, desempenho) |
| `processamento.py` | Fases 1 a 4: aquisição, pré-processamento, segmentação e extração |
| `extrator.py` | Executa a extração do vetor facial em processos paralelos para a tela não travar |
| `reconhecimento.py` | Fase 5: comparação dos vetores faciais e confirmação da identidade |
| `liveness.py` | Prova de vida pela detecção de piscadas (EAR) |
| `controle_acesso.py` | Regras dos níveis 1, 2 e 3, histórico e alertas |
| `relatorios.py` | Indicadores e exportação do histórico para CSV |
| `database.py` | Acesso ao MySQL (inclui a atualização automática de bancos antigos) |
| `autenticacao.py` | Hash PBKDF2-SHA256 das senhas dos administradores |
| `interface.py` | Interface gráfica em CustomTkinter (menu lateral, tema escuro) |
| `schema.sql` | Criação do banco e dados iniciais |

## Área administrativa

As páginas **Cadastro**, **Usuários** e **Relatórios** exigem login de administrador.
- No primeiro acesso, o sistema pede para criar o administrador. A senha precisa ter pelo menos 8 caracteres, com letras e números.
- Voltar para **Acesso ao Cofre** ou clicar em **Bloquear agora** encerra a sessão.
- Três senhas erradas seguidas geram um alerta de segurança.

## Regras de acesso

| Área | Quem entra |
|---|---|
| Arquivo Geral | Todos os níveis |
| Divisão de Toxinas | Só o diretor da Divisão de Toxinas e o ministro |
| Divisão de Biodiversidade | Só o diretor da Divisão de Biodiversidade e o ministro |
| Cofre Central | Só o ministro (existe um único ministro ativo) |

## Como testar

1. Na página **Cadastro**, faça login e cadastre um usuário de cada nível. A pessoa precisa piscar antes da captura, porque fotos não são aceitas.
2. Na página **Acesso ao Cofre**, escolha uma área e clique em **Solicitar acesso**. Fique a até cerca de 60 cm da câmera.
3. Pisque quando o sistema pedir.
4. Tente entrar no **Cofre Central** com um usuário de nível 1: o acesso deve ser negado.
5. Mostre uma foto para a câmera: a prova de vida deve falhar.
6. Faça três tentativas negadas seguidas: um alerta de segurança deve aparecer.
7. Na página **Relatórios e Alertas**, confira o histórico e exporte o CSV.