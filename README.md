# Ofertas do dia: Shopee + Mercado Livre → WhatsApp

Três vezes por dia (7h, 11h e 17h), o GitHub busca os mais vendidos nas APIs oficiais de afiliados.
Depois publica tudo numa página que você abre no iPhone. Em cada oferta, um toque em **Enviar no WhatsApp** já abre o app com a mensagem pronta.

- **Shopee:** 100% automático. O link de afiliado já vem pronto da API.
- **Mercado Livre:** o ML não tem API para gerar link de afiliado. Na primeira vez que for divulgar um produto, gere o link no app do ML e cole na página. Ele fica salvo no seu iPhone.

---

## Configuração (uma vez só, ~20 min)

### 1. Repositório no GitHub
1. Crie uma conta grátis em github.com.
2. Crie um repositório **público** chamado `ofertas`. Público é necessário para o site grátis. Suas senhas ficam nos Secrets e não aparecem.
3. Envie todos os arquivos desta pasta mantendo as pastas (`.github/workflows`, `docs`, `scripts`).

### 2. Credenciais da Shopee
No painel de afiliados (affiliate.shopee.com.br), abra **Open API** e copie o **App ID** e a **Secret**.

### 3. App do Mercado Livre
1. Em developers.mercadolivre.com.br, crie um aplicativo.
2. Em **URI de redirect**, coloque `https://www.google.com`.
3. Copie o **Client ID** e o **Client Secret**.

### 4. Token do GitHub (para o sistema renovar o acesso ao ML sozinho)
1. Abra GitHub → Settings → Developer settings → **Fine-grained tokens** → Generate new token.
2. Em Repository access, escolha só o `ofertas`.
3. Em Permissions, coloque **Secrets: Read and write**.
4. Escolha uma validade longa e copie o token.

### 5. Secrets
No repositório, abra **Settings → Secrets and variables → Actions → New repository secret** e crie:

| Nome | Valor |
|---|---|
| `SHOPEE_APP_ID` | App ID da Shopee |
| `SHOPEE_SECRET` | Secret da Shopee |
| `ML_CLIENT_ID` | Client ID do ML |
| `ML_CLIENT_SECRET` | Client Secret do ML |
| `GH_PAT` | token do passo 4 |

### 6. Autorizar o Mercado Livre
1. Abra no navegador, trocando `SEU_CLIENT_ID`:
   `https://auth.mercadolivre.com.br/authorization?response_type=code&client_id=SEU_CLIENT_ID&redirect_uri=https://www.google.com`
2. Autorize. Você cai no Google com um endereço tipo `google.com/?code=TG-xxxx…`. Copie o que vem depois de `code=`.
3. Em até 10 minutos, abra **Actions → Configurar Mercado Livre → Run workflow**, cole o código e rode.

### 7. Ligar o site
Abra **Settings → Pages → Source: Deploy from a branch → `main` / `/docs`** e salve.

### 8. Primeira busca
Abra **Actions → Buscar ofertas → Run workflow**. Depois de uns 2 minutos, abra `https://SEU_USUARIO.github.io/ofertas/`.
No Safari, toque em **Compartilhar → Adicionar à Tela de Início** para ter o ícone no iPhone.

---

## Uso diário
- **Abas:** Shopee e Mercado Livre. É possível filtrar por categoria e ordenar por mais vendidos, maior comissão, maior desconto ou menor preço.
- **Enviar no WhatsApp:** escolha o grupo ou contato e envie. A oferta fica marcada como "enviado" para você não repetir.
- **✎ Mensagem:** muda o modelo do texto (`{titulo}`, `{preco}`, `{de}`, `{desconto}`, `{link}`).

## Ajustes (arquivo `config.json`)
- `palavras_chave` (Shopee): nichos que você quer buscar. `""` traz o ranking geral.
- `sortType`: `2` = mais vendidos, `5` = maior comissão.
- `comissao_minima_pct`: esconde produtos com comissão abaixo desse valor.
- `categorias` (ML): IDs das categorias do Mercado Livre.

## Se algo der errado
Os erros aparecem num aviso amarelo no topo da página e no log do workflow em **Actions**.
- **"Token do Mercado Livre falhou":** repita o passo 6.
- **Erro da Shopee com "Invalid":** confira o App ID e a Secret.

## Regras dos programas
- **ML:** não use encurtador de links e não divulgue link para a página inicial.
- **WhatsApp:** envie para grupos ou listas de quem pediu para receber. Mandar muita mensagem para quem não pediu pode levar ao bloqueio do número.
