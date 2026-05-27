powershell : 所在位置 行:1 字符: 145
所在位置 行:1 字符: 1
+ powershell -Command "$p = (Get-ChildItem -Path 'G:\' -Recurse -Filter ...
+ ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : NotSpecified: (所在位置 行:1 字符: 145:String) [], RemoteException
    + FullyQualifiedErrorId : NativeCommandError
 
+ ... tion SilentlyContinue | Select-Object -First 1).FullName; if(){ Get-C ...
+                                                                  ~
“if (”后面的 if 语句中缺少条件。
    + CategoryInfo          : ParserError: (:) [], ParentContainsErrorRecordException
    + FullyQualifiedErrorId : IfStatementMissingCondition
 
