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
data &lib.. loan_raw /nolist;
    infile "&source_path/loan_raw&file_sfx" recfm=F lrecl=657;
    input
  @1    		CustomerId		PK2.0
 @3   		'Loan Amount'		PK2.0
 @5   		'Funded Amount'	PK2.0
 @8   		'Funded Amount Investor'		PK3.0
 @10  		Term		S370FPD2.0
 @13  		'Batch Enrolled'		$EBCDIC3.
 @19  		'Interest Rate'		S370FPD6.0
 @25  		Grade		S370FPD6.0
 @32  		'Sub Grade'		S370FPD7.0
 @39  		'Employment Duration'		S370FPD7.0
 @40  		'Home Ownership'		PK1.0
 @41  		'Verification Status'		PK1.0
 @48  		'Payment Plan'		S370FPD7.0
 @55  		'Loan Title'		S370FPD7.0
 @57  		'Debit to Income'		S370FPD2.0
 @58  		'Delinquency - two years'		$EBCDIC1.
 @61  		'Inquires - six months'		S370FPD3.0
 @64  		'Open Account'		S370FPD3.0
 @67  		'Public Record'		$EBCDIC3.
 @73  		'Revolving Balance'		S370FPD6.0
 @79  		'Revolving Utilities'		S370FPD6.0
 @86  		'Total Accounts'		S370FPD7.0
 @93  		'Initial List Status'		S370FPD7.0
 @94  		'Total Received Interest'		PK1.0
 @95  		'Total Received Late Fee'		PK1.0
 @102 		'Recoveries'		S370FPD7.0
 @109 		'Collection Recovery Fee'		S370FPD7.0
 @111 		'Collection 12 months Medical'		S370FPD2.0
 @112 		'Application Type'		$EBCDIC1.
 @115 		'Last week Pay'		S370FPD3.0
 @118 		'Accounts Delinquent'		S370FPD3.0
 @121 		'Total Collection Amount'		$EBCDIC3.
 @127 		'Total Current Balance'		S370FPD6.0
 @133 		'Total Revolving Credit Limit'		S370FPD6.0
 @140 		'Loan Status'		S370FPD7.0

    ;
run;

