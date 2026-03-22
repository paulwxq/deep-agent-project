/* ============================================================
   02_loan_transform.sas
   Purpose : Transform loan application data from a single source.
             Demonstrates column renames and derived columns.
   Source  : train_1.csv
   Output  : loan_out.csv
   ============================================================ */

%LET data_path   = /path/to/doc/data;
%LET output_path = /path/to/sas/output;

/* ------------------------------------------------------------ */
/* Step 1 - Import source CSV                                   */
/* NOTE: Row 1 is a Chinese Excel artifact; headers on row 2.  */
/* NOTE: SAS converts spaces in column names to underscores,   */
/*       e.g. "Loan Amount" becomes Loan_Amount after import.  */
/* ------------------------------------------------------------ */
/*PROC IMPORT DATAFILE="&data_path./train_1.csv"
    OUT     = loan_raw
    DBMS    = CSV
    REPLACE;
    NAMEROW  = 2;
    STARTROW = 3;
    GETNAMES = YES;
RUN;*/

/* ------------------------------------------------------------ */
/* Step 2 - Rename columns and add derived columns              */
/* Renames                                                      */
/*   Loan_Amount     -> loan_amt                                */
/*   Interest_Rate   -> int_rate                                */
/*   Debit_to_Income -> dti                                     */
/* ------------------------------------------------------------ */
DATA loan_out;
    SET loan_raw (RENAME=(Loan_Amount     = loan_amt
                           Interest_Rate   = int_rate
                           Debit_to_Income = dti));

    /* Derived: 1 if loan grade is A or B (low risk) */
    high_grade_flag = (Grade in ('A', 'B'));

    /* Derived: interest rate expressed as a decimal proportion */
    int_rate_pct = int_rate / 100;

    KEEP CustomerId Grade Sub_Grade Employment_Duration
         Home_Ownership Loan_Status
         loan_amt int_rate dti
         high_grade_flag int_rate_pct;
RUN;

/* ------------------------------------------------------------ */
/* Step 3 - Export output CSV                                   */
/* ------------------------------------------------------------ */
PROC EXPORT DATA    = loan_out
            OUTFILE = "&output_path./loan_out.csv"
            DBMS    = CSV
            REPLACE;
RUN;
