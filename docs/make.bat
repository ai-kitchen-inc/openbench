@ECHO OFF

pushd %~dp0

set SOURCEDIR=.
set BUILDDIR=_build

if "%SPHINXBUILD%" == "" (
	set SPHINXBUILD=python -m sphinx
)

if "%1" == "" goto help

%SPHINXBUILD% -M %1 %SOURCEDIR% %BUILDDIR% %SPHINXOPTS%
goto end

:help
%SPHINXBUILD% -M help %SOURCEDIR% %BUILDDIR% %SPHINXOPTS%

:end
popd
