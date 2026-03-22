/* ============================================================
   01_churn_transform.sas
   Purpose : Transform customer churn data from a single source.
             Demonstrates column renames and derived columns.
   Source  : churn_modeling_1.csv
   Output  : churn_out.csv
   ============================================================ */

%LET data_path   = /path/to/doc/data;
%LET output_path = /path/to/sas/output;

/* ------------------------------------------------------------ */
/* Step 1 - Import source CSV                                   */
/* NOTE: Row 1 of the file is a Chinese Excel artifact          */
/*       ("biao ge 1"). Row 2 contains column headers;          */
/*       data rows begin on row 3.                              */
/* ------------------------------------------------------------ */
/*PROC IMPORT DATAFILE="&data_path./churn_modeling_1.csv"
    OUT     = churn_raw
    DBMS    = CSV
    REPLACE;
    NAMEROW  = 2;
    STARTROW = 3;
    GETNAMES = YES;
RUN;*/

/* ------------------------------------------------------------ */
/* Step 2 - Rename columns and add derived columns              */
/* Renames                                                      */
/*   CreditScore    -> credit_scr                               */
/*   EstimatedSalary -> est_sal                                  */
/*   NumOfProducts  -> num_prod                                 */
/* ------------------------------------------------------------ */
DATA churn_out;
    SET churn_raw (RENAME=(CreditScore     = credit_scr
                            EstimatedSalary = est_sal
                            NumOfProducts   = num_prod));

    /* Derived: balance per product held */
    bal_per_prod = Balance / num_prod;

    /* Derived: 1 if customer is aged 60 or above */
    senior_flag  = (Age >= 60);

    KEEP CustomerId Geography Gender Age Tenure Balance Exited
         credit_scr est_sal num_prod
         bal_per_prod senior_flag;
RUN;

/* ------------------------------------------------------------ */
/* Step 3 - Export output CSV                                   */
/* ------------------------------------------------------------ */
PROC EXPORT DATA    = churn_out
            OUTFILE = "&output_path./churn_out.csv"
            DBMS    = CSV
            REPLACE;
RUN;
