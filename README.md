
# InventoryPro – Tali's Bread & Pastries

InventoryPro is a web-based Inventory and Order Management System for Tali's Bread & Pastries.

The system includes product browsing, customer ordering, inventory management, staff management, delivery rider assignments, and analytics.

## Technologies Used

- Python
- Flask
- MySQL / MariaDB
- HTML, CSS, JavaScript
- Bootstrap (if applicable)

## Requirements

- Python
- MySQL or MariaDB Server
- MySQL Workbench (optional)
- Git
- Python dependencies listed in `requirements.txt`

## Local Setup

### 1. Clone the repository

```bash
git clone https://github.com/zyonto/InventoryPro.git
cd InventoryPro
```

### 2. Create a virtual environment

```bash
python -m venv venv
```

Activate the environment on Windows:

```powershell
.\venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
python -m pip install -r requirements.txt
```

### 4. Set up the database

1. Start MySQL or MariaDB.
2. Open MySQL Workbench.
3. Create a database named `inventorypro_db`, if it does not already exist.
4. Import the provided database SQL backup using **Server > Data Import**.
5. Confirm that all required tables have been imported.

**Note:** The database backup is provided separately and is not included in this public repository.

### 5. Configure environment variables

Create a `.env` file in the project's root directory.

```dotenv
SECRET_KEY=replace-with-your-own-secret-key

MYSQL_HOST=localhost
MYSQL_USER=root
MYSQL_PASSWORD=your-database-password
MYSQL_DB=inventorypro_db

MAIL_USERNAME=your-email@gmail.com
MAIL_PASSWORD=your-gmail-app-password
```

Do not upload `.env` or passwords to GitHub.

### 6. Run the application

```bash
flask --app app run --debug
```

Open the website in a browser:

http://127.0.0.1:5000/

## Main Features

- Customer registration and login
- Email OTP verification
- Product catalog and shopping cart
- Customer checkout and order history
- Inventory and recipe management
- Order status tracking
- Bakery staff management
- Delivery rider assignment
- Analytics and reporting
- COD and GCash demo payment workflows

## Payment Note

The GCash mock payment feature is intended for local demonstration only. It does not process actual GCash transactions.

## Project Purpose

Developed as an academic capstone project for inventory and order management at Tali's Bread & Pastries.
```
