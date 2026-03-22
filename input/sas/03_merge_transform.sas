/* ============================================================
   03_merge_transform.sas
   Purpose : Join churn and loan datasets on the shared key
             CustomerId, then add cross-source derived columns.
             Demonstrates multi-source merges and expressions
             that reference columns from different input files.
   Sources : churn_modeling_1.csv, train_1.csv
   Output  : merged_out.csv
   ============================================================ */

%LET data_path   = /path/to/doc/data;
%LET output_path = /path/to/sas/output;

/* ------------------------------------------------------------ */
/* Step 1 - Import both source CSVs                            */
/* ------------------------------------------------------------ */
/*PROC IMPORT DATAFILE="&data_path./churn_modeling_1.csv"
    OUT     = churn_raw
    DBMS    = CSV
    REPLACE;
    NAMEROW  = 2;
    STARTROW = 3;
    GETNAMES = YES;
RUN;

PROC IMPORT DATAFILE="&data_path./train_1.csv"
    OUT     = loan_raw
    DBMS    = CSV
    REPLACE;
    NAMEROW  = 2;
    STARTROW = 3;
    GETNAMES = YES;
RUN;
*/
/* ------------------------------------------------------------ */
/* Step 2a - Prepare churn dataset                             */
/*   Rename: CreditScore -> credit_scr                         */
/*   Select relevant columns only                              */
/* ------------------------------------------------------------ */
DATA churn_prep;
    SET churn_raw (RENAME=(CreditScore = credit_scr));
    KEEP CustomerId credit_scr Age Balance Exited;
RUN;

/* ------------------------------------------------------------ */
/* Step 2b - Prepare loan dataset                              */
/*   Rename: Loan_Amount     -> loan_amt                       */
/*           Debit_to_Income -> dti                            */
/*   Select relevant columns only                              */
/* ------------------------------------------------------------ */
DATA loan_prep;
    SET loan_raw (RENAME=(Loan_Amount     = loan_amt
                           Debit_to_Income = dti));
    KEEP CustomerId loan_amt dti Grade Loan_Status;
RUN;

/* ------------------------------------------------------------ */
/* Step 3 - Sort both datasets by merge key                    */
/* ------------------------------------------------------------ */
PROC SORT DATA=churn_prep; BY CustomerId; RUN;
PROC SORT DATA=loan_prep;  BY CustomerId; RUN;

/* ------------------------------------------------------------ */
/* Step 4 - Merge and add cross-source derived columns         */
/* ------------------------------------------------------------ */
DATA merged_out;
    MERGE churn_prep (IN=a)
          loan_prep  (IN=b);
    BY CustomerId;
    IF a AND b;

    /* Derived: credit-adjusted debt risk score
       Draws on credit_scr (from churn_modeling_1.csv / CreditScore)
       and dti (from train_1.csv / Debit_to_Income)              */
    risk_score = credit_scr - (dti * 10);

    /* Derived: customer age scaled relative to loan size
       Draws on Age (from churn_modeling_1.csv)
       and loan_amt (from train_1.csv / Loan_Amount)             */
    age_loan_ratio = (Age / loan_amt) * 1000;

    KEEP CustomerId credit_scr Age Balance Exited
         loan_amt dti Grade Loan_Status
         risk_score age_loan_ratio;
RUN;

/* ------------------------------------------------------------ */
/* Step 5 - Export output CSV                                  */
/* ------------------------------------------------------------ */
PROC EXPORT DATA    = merged_out
            OUTFILE = "&output_path./merged_out.csv"
            DBMS    = CSV
            REPLACE;
RUN;
