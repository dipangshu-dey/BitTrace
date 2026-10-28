# BitTrace: Bitcoin Transaction Forensics and Investigation System

## Overview

BitTrace is a Python-based Bitcoin transaction forensics and investigation system developed to analyse Bitcoin addresses, explore transaction relationships, identify potentially suspicious transaction patterns, and present investigation findings through an interactive dashboard.

The application brings multiple blockchain investigation features together in one place. Users can initiate investigations, explore transaction graphs, review transaction activity over time, examine statistical summaries, and ask investigation-related questions through an AI assistant.

BitTrace is designed as an educational project to demonstrate how blockchain data analysis and visualisation can support Bitcoin transaction investigations.

## Objectives

The main objectives of BitTrace are:

- To investigate Bitcoin addresses and analyse related transaction activity.
- To visualise relationships between Bitcoin addresses and transactions.
- To identify transaction patterns that may require further investigation.
- To group potentially related Bitcoin addresses using available analytical methods.
- To calculate and display address risk scores with supporting findings.
- To present transaction activity through graphs, timelines, and statistical summaries.
- To maintain a history of investigations where supported by the application.
- To generate PDF reports containing investigation findings.
- To provide an AI assistant for understanding investigation results.

## Features

### 1. Bitcoin Investigation

The investigation module allows users to enter a Bitcoin address and initiate an investigation.

Users can configure the maximum number of transaction hops to analyse and add optional investigation notes. The application processes the available data and presents the resulting investigation findings.

### 2. Transaction Graph Explorer

The Graph Explorer provides a visual representation of relationships between Bitcoin addresses and transaction flows.

It helps users explore connections within the investigated transaction graph, search for addresses, and inspect available address details.

### 3. Address Clustering

Address clustering analyses transaction relationships to identify groups of addresses that may be associated with the same wallet or entity.

The results are analytical estimates and do not independently prove common ownership.

### 4. Transaction Pattern Detection

BitTrace supports the analysis of transaction patterns that may be relevant during a blockchain investigation, including:

- Fan-in patterns
- Fan-out patterns
- Peel chains
- CoinJoin-like transaction patterns
- Circular transaction flows

These patterns can help investigators identify transaction structures that deserve closer examination. A detected pattern alone does not establish illegal activity.

### 5. Transaction Timeline

The Timeline module presents available transaction activity over time.

It provides an interactive view of incoming, outgoing, and related transactions, helping users understand the sequence and distribution of transaction activity.

### 6. Investigation History

The History module allows users to review previously recorded investigations supported by the application.

This helps users revisit earlier investigation results without having to treat every investigation as a completely new case.

### 7. Statistics Dashboard

The Statistics module presents aggregated information from available investigations.

Depending on the selected data, it can display investigation counts, scored addresses, risk distributions, and detected transaction patterns.

### 8. AI Investigation Assistant

The AI Assistant provides an interface for asking questions about an investigation in natural language.

The application integrates with Ollama for local language-model processing. The assistant can help explain transaction flows, summarise findings, and answer questions using available investigation information.

AI-generated interpretations should be checked against the recorded investigation data.

### 9. Forensic Report Generation

BitTrace includes PDF report-generation functionality for presenting available investigation information in a structured format.

The report can help organise investigation findings for documentation and review.

## Technology Stack

The project uses the following technologies and components:

| Technology | Purpose |
|---|---|
| Python | Main programming language |
| Streamlit | Web-based application interface |
| SQLite | Local database storage |
| Ollama | Local AI model integration |
| Graph visualisation libraries | Visual representation of transaction relationships |
| ReportLab | PDF report generation |
| Python libraries for blockchain data processing | Retrieving and analysing available transaction information |

The exact libraries and versions depend on the project's source code and `requirements.txt`.

## Application Screenshots

The following screenshots show the main modules of the BitTrace application.

### Home Page

The Home page introduces BitTrace and presents its main investigation objectives and navigation options.

![BitTrace Home Page](bittrace/docs/screenshots/01-home.png.png)

### Investigation Workspace

The Investigation page allows users to enter a Bitcoin address, configure the investigation depth, and start an investigation.

![Investigation Workspace](bittrace/docs/screenshots/02-investigation.png.png)

### Graph Explorer

The Graph Explorer visualises address relationships and transaction flows within an investigation.

![Graph Explorer](bittrace/docs/screenshots/03-graph-explorer.png.png)

### Transaction Timeline

The Timeline page displays transaction activity over time, including available incoming, outgoing, and related transaction information.

![Transaction Timeline](bittrace/docs/screenshots/04-timeline.png.png)

### Statistics Dashboard

The Statistics page displays aggregate investigation information, risk distributions, and detected transaction patterns.

![Statistics Dashboard](bittrace/docs/screenshots/05-statistics.png.png)

### AI Investigation Assistant

The AI Assistant provides an interface for asking questions about recorded investigation findings using the configured local AI model.

![AI Investigation Assistant](bittrace/docs/screenshots/06-ai-assistant.png.png)

## Project Structure

The following structure represents the main directories and files of the project. Some internal files are omitted for readability.

```text
BitTrace/
├── bittrace/
│   ├── ai/
│   ├── app/
│   ├── assets/
│   │   └── bittrace.png
│   ├── core/
│   ├── data/
│   ├── db/
│   ├── docs/
│   │   └── screenshots/
│   ├── reports/
│   ├── tests/
│   ├── config.py
│   ├── requirements.txt
│   ├── ui_theme.py
│   ├── run_bittrace.bat
│   └── run_bittrace_lan.bat
├── .gitignore
└── README.md
```

This is a simplified representation. The exact directory structure may differ depending on how the repository is organised.

## System Requirements

The general requirements for running BitTrace are:

- Windows or another operating system supported by the project's dependencies.
- A compatible Python version.
- The required Python packages.
- Internet access when live blockchain data retrieval requires it.
- Ollama and a compatible model if the AI Assistant is enabled.

The exact Python version and configuration should be checked against the project's dependencies.

## Installation and Setup

### 1. Clone the Repository

Open a terminal and run:

```bash
git clone https://github.com/dipangshu-dey/BitTrace.git
cd BitTrace
```

The repository URL assumes that the GitHub repository is named `BitTrace` under the account `dipangshu-dey`.

### 2. Create a Virtual Environment

A virtual environment keeps the project's Python packages separate from other Python installations.

For Windows PowerShell, run:

```powershell
py -3.10 -m venv venv
```

Use the Python version required by the project if it differs from Python 3.10.

### 3. Install Dependencies

Activate the virtual environment:

```powershell
.\venv\Scripts\Activate.ps1
```

Then install the dependencies:

```powershell
python -m pip install -r requirements.txt
```

If PowerShell prevents activation, you can run the virtual environment's Python executable directly:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 4. Start the Application

Run the following command from the project directory:

```powershell
.\venv\Scripts\python.exe -m streamlit run app\Home.py
```

If the repository uses a different application entry point, use the launch command provided by the project.

### 5. Open BitTrace

After starting the application, Streamlit displays a local address in the terminal. Open that address in your browser to access BitTrace.

Additional setup may be necessary for live blockchain data retrieval and AI functionality.

## How to Use BitTrace

1. Start the BitTrace application.
2. Open the Investigate page from the sidebar.
3. Enter a Bitcoin address.
4. Select the investigation depth and provide optional notes.
5. Run the investigation.
6. Review the available investigation findings.
7. Open Graph Explorer to examine address relationships.
8. Open Timeline to review transaction activity over time.
9. Use History to revisit previously recorded investigations.
10. Review the Statistics dashboard for aggregate results.
11. Open AI Assistant to ask questions about a recorded investigation, if the local AI service is available.
12. Generate a PDF report when the report-generation functionality is available.

The information displayed depends on the selected address, the data retrieved, and the application's configuration.

## Testing

Testing should cover the main components of BitTrace, including:

- Bitcoin address validation.
- Blockchain data retrieval and error handling.
- Transaction processing.
- Address clustering.
- Transaction pattern detection.
- Risk-score calculation.
- Graph generation.
- Investigation history.
- PDF report generation.
- AI Assistant integration.

Only tests that have actually been executed should be reported as completed. The presence of a test file does not, by itself, confirm that the application has passed the tests.

## Limitations

BitTrace has several limitations that should be considered when interpreting investigation results:

- Address clustering may identify potential relationships but cannot independently confirm wallet ownership.
- Transaction patterns may have legitimate explanations and should not automatically be considered evidence of criminal activity.
- Live blockchain data retrieval may depend on external services and network availability.
- Risk scores depend on the application's analytical rules and available information.
- AI-generated explanations may be inaccurate and should be verified against the underlying data.
- Identifying the real-world person or organisation controlling a Bitcoin address requires additional evidence.
- The completeness of an investigation depends on the data sources and analysis available to the application.

## Future Scope

Potential areas for future development include:

- Integration with additional blockchain data sources.
- Improvements to transaction graph exploration.
- Enhanced transaction pattern analysis.
- Additional investigation and reporting options.
- Improved error handling and automated testing.
- Expanded threat-intelligence integration.
- Further improvements to AI-assisted investigation workflows.

These are possible future enhancements and should not be interpreted as features that are already implemented.

## Developer

**Dipangshu Dey**

MSc Cyber Security  
National Forensic Sciences University (NFSU)

GitHub: https://github.com/dipangshu-dey

LinkedIn: https://www.linkedin.com/in/dipangshu-dey-251a80264/

## Disclaimer

BitTrace is an educational blockchain analysis and cybersecurity project. It is intended to support the examination and visualisation of Bitcoin transaction activity.

Investigation results are analytical outputs and should not be treated as conclusive proof of criminal activity or definitive identification of a Bitcoin address owner.