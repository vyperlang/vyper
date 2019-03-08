@echo off
if "%1"=="init" goto :init
if "%1"=="test" goto :test
rem Default
if "%1"=="" goto :init

:error
echo Unknown parameters: %*
echo Expected: init test 
rem echo Expect: test lint clean clean-pyc clean-build clean-test docs docker-build
goto :end

:init
python setup.py install
goto :end

:test
python setup.py test
goto :end

rem TODO: clean, etc (for recursive delete, use robocopy to move to temp dir, then delete temp dir)

:end
