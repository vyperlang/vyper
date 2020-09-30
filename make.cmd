@echo off
if "%1"=="init" goto :init
if "%1"=="test" goto :test
if "%1"=="dev-deps" goto :dev-deps
if "%1"=="lint" goto :lint
if "%1"=="docs" goto :docs
if "%1"=="freeze" goto :freeze
if "%1"=="clean" goto :clean
if "%1"=="clean-build" goto :clean-build
if "%1"=="clean-pyc" goto :clean-pyc
if "%1"=="clean-test" goto :clean-test
rem Default
if "%1"=="" goto :init

:error
echo Unknown parameters: %*
echo Expected: init test lint clean clean-pyc clean-build clean-test docs
rem echo Expect: test lint clean clean-pyc clean-build clean-test docs docker-build
goto :end

:init
python setup.py install
goto :end

:test
python setup.py test
goto :end

:dev-deps
python -m pip install .[test,lint]
goto :end

:lint
tox -e lint
goto :end

:docs
CALL docs\make clean
CALL docs\make html
START docs\_build\html\index.html
goto :end

:freeze
CALL :clean
CALL :init
set PYTHONPATH=.
for /f "delims=" %%a in ('python vyper/cli/vyper_compile.py --version') do @set VERSION=%%a
pyinstaller --clean --onefile vyper/cli/vyper_compile.py --name vyper.%VERSION%.windows --add-data vyper;vyper
goto :end

:clean
CALL :clean-build
CALL :clean-pyc
CALL :clean-test
goto :end

:clean-build
if exist build RMDIR /Q /S build
if exist dist RMDIR /Q /S dist
for /d %%x in (*.egg-info) do if exist "%%x" RMDIR /Q /S "%%x"
for /r %%x in (*.spec) do del %%x
goto :end


:clean-pyc
for /r %%x in (*.pyc) do del %%x
for /r %%x in (*.pyo) do del %%x
for /r %%x in (*~) do del %%x
for /r /d %%x in (__pycache__) do if exist "%%x" RMDIR "%%x"
goto :end


:clean-test
for /r /d %%x in (htmlcov) do if exist "%%x" RMDIR /Q /S "%%x"
goto :end

:end
