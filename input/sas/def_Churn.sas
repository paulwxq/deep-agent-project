/***********************************************************************
*  COPYRIGHT. THE HONGKONG AND SHANGHAI BANKING CORPORATION   
*  LIMITED 2016. ALL RIGHTS RESERVED.                         
*                                                             
*  THIS SOFTWARE IS ONLY TO BE USED FOR THE PURPOSE FOR WHICH 
*  IT HAS BEEN PROVIDED.  NO PART OF IT IS TO BE REPRODUCED,  
*  DISASSEMBLED, TRANSMITTED, STORED IN A RETRIEVAL SYSTEM,   
*  NOR TRANSLATED IN ANY HUMAN OR COMPUTER LANGUAGE IN ANY    
*  WAY OR FOR ANY PURPOSES WHATSOEVER WITHOUT THE PRIOR       
*  WRITTEN CONSENT OF THE HONGKONG AND SHANGHAI BANKING       
*  CORPORATION LIMITED.  INFRINGEMENT OF COPYRIGHT IS A       
*  SERIOUS CIVIL AND CRIMINAL OFFENCE, WHICH CAN RESULT IN    
*  HEAVY FINES AND PAYMENT OF SUBSTANTIAL DAMAGES.
************************************************************************
*
*  Common Program for SAS (AMH version)
*
*  Program ID      def_CACST
*  Author          Cindy Lo
*  Date Written    SEP 2016
*
*  Description
*      Define CACST - CIF Account Statistics File
*
*  Amendment History
*
*
************************************************************************/

/* Set parameters here or in calling program, as appropriate */
/*
libname DAT "/sasdata/hsbc/user/GBLINA/hkgiaa/xxxxx";

%let source_path=/sasdata/hsbc/user/GBLINA/hkgiaa/xxxxx;
%let file_sfx=;

%let lib=DAT;
*/


/*data &lib..CACST /nolist;*/
data &lib.. churn_raw /nolist;

    infile "&source_path/churn_raw&file_sfx" recfm=F lrecl=657;
    input
        @1    CustomerId                       PK2.0
        @3    Surname                           PK2.0
        @5    CreditScore                             PK3.0
        @8    Geography                              S370FPD2.0
        @10   Gender                       $EBCDIC3.
        @13   Age                  S370FPD6.0
        @19   Tenure                   S370FPD6.0
        @25   Balance               S370FPD7.0
        @32   NumOfProducts               S370FPD7.0
        @39   HasCrCard               PK1.0
        @40   IsActiveMember               PK1.0
        @41   EstimagteSalary                   S370FPD7.0
        @48   Exited                    S370FPD7.0
    ;
run;

