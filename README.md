# Sherlock Flask

Uma aplicação web em **Flask** que utiliza a poderosa ferramenta **Sherlock** para buscar perfis de usuários em mais de 300 plataformas sociais e sites. Esta ferramenta de **OSINT** (Open Source Intelligence) oferece uma interface simples para que qualquer pessoa possa verificar a existência de um nome de usuário em um grande número de redes.

---

## Recursos

* **Busca em Múltiplas Plataformas:** Verifique a disponibilidade de um nome de usuário em centenas de sites com um único clique.
* **Interface Web Intuitiva:** Uma interface simples e limpa construída com Flask.
* **Resultados Rápidos:** Exibe os resultados em tempo real, indicando quais perfis foram encontrados e quais não existem.

---

## Tecnologias

* **Python 3.x**
* **Flask**
* **Sherlock**

---

## Instalação e Uso

Siga estes passos para ter o projeto rodando localmente.

### 1. Pré-requisitos

Certifique-se de ter o **Python 3.x** e o `pip` instalados em sua máquina.

### 2. Clonar o Repositório

```bash
git clone [(https://github.com/danielambrosim/flask-detective.git)]
cd sherlock-flask
```

### 3. Criar e Ativar o Ambiente Virtual
É uma boa prática isolar as dependências do projeto.

```bash
# Para Linux/macOS
python3 -m venv venv
source venv/bin/activate

# Para Windows
python -m venv venv
venv\Scripts\activate
```

### 4. Instalar as Dependências
Com o ambiente virtual ativado, instale as bibliotecas necessárias.
```bash
pip install -r requirements.txt
```

### 5. Rodar a Aplicação
Inicie o servidor de desenvolvimento do Flask.

```bash
flask run
```
