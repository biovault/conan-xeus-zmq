from conans import ConanFile, tools
from conan.tools.cmake import CMakeDeps, CMake, CMakeToolchain
from conan.tools import files
from conans.tools import SystemPackageTool, load, save
from conan.errors import ConanException
import os
from shutil import copytree, ignore_patterns, copytree, move, rmtree
from pathlib import Path, PurePosixPath
import subprocess

required_conan_version = ">=1.60.0"


class XeusZmqConan(ConanFile):
    python_requires = "bundleutils/0.1@lkeb/stable"
    python_requires_extend = "bundleutils.BundleUtils"

    name = "xeus-zmq"
    version = "1.1.1"
    license = "MIT"
    author = "B. van Lew b.van_lew@lumc.nl"
    url = "https://github.com/jupyter-xeus/xeus-zmq.git"
    zmqurl = "https://github.com/zeromq/libzmq.git"
    zmqversion = "v4.3.5"
    cppzmqurl = "https://github.com/zeromq/cppzmq.git"
    cppzmqversion = "v4.10.0"

    description = """xeus-zmq provides various implementations
    of the xserver API from xeus, based on the ZeroMQ library."""
    topics = ("python", "jupyter", "zeromq", "zeus")
    settings = "os", "compiler", "build_type", "arch"
    options = {"shared": [True, False], "testing": [True, False], 'merge_package': [True, False]}
    default_options = {"shared": True, "testing": False, 'merge_package': False}
    generators = "CMakeDeps"
    exports = "cmake/*"
    exports_sources = "Findlibsodium.cmake", "Findzeromq.cmake"
    requires = (
        "nlohmann_json/3.11.3", # header only
    #    "cppzmq/4.10.0", # header only but depends on binary dep zeromq
    #    "zeromq/4.3.5@lkeb/stable", # The biovault multi-config conan-zeromq with cmake config 
        "xeus/3.1.4@lkeb/stable" # The biovault multi-config xeus with cmake config 
    )
   
    def init(self):
        # use the buntilutils to record the 
        # original source directory
        self._save_git_path()

    def source(self):
        try:
            self.run(f"git clone {self.url}")
        except ConanException as e:
            print(e)
        os.chdir("./xeus-zmq")
        try:
            self.run(f"git checkout tags/{self.version}")
        except ConanException as e:
            print(e)

        # Add the dependency cppzmq as a subdirectory
        self.run(f"git clone {self.zmqurl}")
        os.chdir("./libzmq")
        self.run(f"git checkout tags/{self.zmqversion}")
        os.chdir('..')

        self.run(f"git clone {self.cppzmqurl}")
        os.chdir("./cppzmq")
        self.run(f"git checkout tags/{self.cppzmqversion}")
        os.chdir('..')

        subdirs = """
add_subdirectory(libzmq)
add_subdirectory(cppzmq)
"""
        ## for CMP0091 policy set xeus CMake version to 3.15
        xeuszmqcmake = os.path.join(self.source_folder, "xeus-zmq", "CMakeLists.txt")
        tools.replace_in_file(xeuszmqcmake, "cmake_minimum_required(VERSION 3.8)", "cmake_minimum_required(VERSION 3.15)")
        # Match the name of the xeus link target with the package
        #tools.replace_in_file(os.path.join(self.source_folder, "xeus-zmq", "CMakeLists.txt"), "set(XEUS_TARGET_NAME xeus-static)", "set(XEUS_TARGET_NAME libxeus-static)")
        #tools.replace_in_file(os.path.join(self.source_folder, "xeus-zmq", "CMakeLists.txt"), "set(XEUS_TARGET_NAME xeus)", "set(XEUS_TARGET_NAME xeus::xeus)")
        tools.replace_in_file(xeuszmqcmake, "find_package(xeus ${xeus_REQUIRED_VERSION} REQUIRED)", "find_package(xeus ${xeus_REQUIRED_VERSION} REQUIRED)\n message(\"xeus found ${xeus_FOUND} - inc ${xeus_INCLUDE_DIRS} libs ${xeus_LIBRARY} & ${xeus_STATIC_LIBRARY} \")")
        tools.replace_in_file(xeuszmqcmake, "find_package(cppzmq ${cppzmq_REQUIRED_VERSION} REQUIRED)", "find_package(cppzmq ${cppzmq_REQUIRED_VERSION} REQUIRED) \n message(\"cppzmq found ${cppzmq_FOUND} - inc ${cppzmq_INCLUDE_DIRS} libs ${cppzmq_LIBRARY} & ${cppzmq_STATIC_LIBRARY} \")")
        # Fix XEUS_ZMQ_CMAKECONFIG_INSTALL_DIR
        tools.replace_in_file(xeuszmqcmake, "${CMAKE_INSTALL_LIBDIR}/cmake/${PROJECT_NAME}", "lib/cmake/${PROJECT_NAME}")
        # Match the versions in the CMake with our versions (there are no major changes)
        tools.replace_in_file(xeuszmqcmake, "set(xeus_REQUIRED_VERSION 3.1.1)", "set(xeus_REQUIRED_VERSION 3.1.4)")
        tools.replace_in_file(xeuszmqcmake, "set(zeromq_REQUIRED_VERSION 4.3.2)", "set(zeromq_REQUIRED_VERSION 4.3.5)")
        tools.replace_in_file(xeuszmqcmake, "set(zeromq_REQUIRED_VERSION 4.3.5)", f"set(zeromq_REQUIRED_VERSION 4.3.5)\n{subdirs}")
        # Separate binary targets by CONFIG subdir
        tools.replace_in_file(xeuszmqcmake, "ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}", "ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}/$<CONFIG>")
        tools.replace_in_file(xeuszmqcmake, "LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}", "LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}/$<CONFIG>")
        tools.replace_in_file(xeuszmqcmake, "RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}", "RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}/$<CONFIG>")
        # Link zeromq using libzmq as in out dependency 
        tools.replace_in_file(xeuszmqcmake, "PUBLIC ${CPPZMQ_TARGET_NAME}", "PUBLIC libzmq\n        PUBLIC ${CPPZMQ_TARGET_NAME}")
        dep_text = """
add_dependencies(xeus-zmq-static xeus-zmq cppzmq libzmq)
"""
        with open(xeuszmqcmake, "a") as cmakefile:
            cmakefile.write(dep_text)

        os.chdir("..")

    def _get_tc(self):
        """Generate the CMake configuration using
        multi-config generators on all platforms, as follows:

        Windows - defaults to Visual Studio
        Macos - XCode
        Linux - Ninja Multi-Config

        CMake needs to be at least 3.17 for Ninja Multi-Config

        Returns:
            CMakeToolchain: a configured toolchain object
        """
        generator = None
        if self.settings.os == "Macos":
            generator = "Xcode"

        if self.settings.os == "Linux":
            generator = "Ninja Multi-Config"

        tc = CMakeToolchain(self, generator=generator)
        tc.variables["BUILD_TESTING"] = "ON" if self.options.testing else "OFF"
        tc.variables["BUILD_SHARED_LIBS"] = "ON" if self.options.shared else "OFF"
        tc.variables["CMAKE_PREFIX_PATH"] = Path(self.build_folder).as_posix()
        tc.variables["WITH_PERF_TOOL"] = "OFF" # zmq
        tc.variables["BUILD_TESTS"] = "OFF" #zmq

        if self.settings.os == "Linux":
            tc.variables["CMAKE_CONFIGURATION_TYPES"] = "Debug;Release"

        if self.settings.os == "Macos":
            proc = subprocess.run(
                "brew --prefix libomp", shell=True, capture_output=True
            )
            prefix_path = f"{proc.stdout.decode('UTF-8').strip()}"
            tc.variables["OpenMP_ROOT"] = prefix_path

        xeuspath = Path(self.deps_cpp_info["xeus"].rootpath).as_posix()
        tc.variables["xeus_ROOT"] = xeuspath
        print(f"********xeus_root: {xeuspath}**********")
        return tc
    
    def configure(self):
        # Force the zmq to use the shared lib
        self.options["zeromq"].shared = True

    def system_requirements(self):
        if self.settings.os == "Macos":
            installer = SystemPackageTool()
            installer.install("libomp")
            # Make the brew OpenMP findable with a symlink
            proc = subprocess.run("brew --prefix libomp",  shell=True, capture_output=True)
            subprocess.run(f"ln {proc.stdout.decode('UTF-8').strip()}/lib/libomp.dylib /usr/local/lib/libomp.dylib", shell=True)

    def generate(self):
        # 
        deps = CMakeDeps(self)
        deps.generate()
        tc = self._get_tc()
        tc.generate()

        #     {Path(self.deps_cpp_info['cppzmq'].rootpath, 'include').as_posix()}
        #     {Path(self.deps_cpp_info['zeromq'].rootpath, 'include').as_posix()}
        with open("conan_toolchain.cmake", "a") as toolchain:
            toolchain.write(
                fr"""
include_directories(
    {Path(self.deps_cpp_info['nlohmann_json'].rootpath, 'include').as_posix()}
    {Path(self.deps_cpp_info['xeus'].rootpath, 'include').as_posix()}
    {Path(self.deps_cpp_info['xtl'].rootpath, 'include').as_posix()}
)
            """
            )

    def _configure_cmake(self):
        cmake = CMake(self)
        cmake.verbose = True
        print(f"Source folder {Path(self.source_folder).as_posix()}")
        try:
            cmake.configure(build_script_folder="xeus-zmq") #, cli_args=["--trace"])
        except ConanException as e:
            print(f"Exception: {e} from cmake invocation: \n Completing configure")

        return cmake

    def build(self):
        self._save_package_id()
        # Build both release and debug for dual packaging
        cmake = self._configure_cmake()
        # conan cmake.install sts the package directory as the install prefix 
        # and uses the build_type as source
        cmake.build(build_type="Debug")
        cmake.install(build_type="Debug")

        cmake = self._configure_cmake()

        cmake.build(build_type="Release")
        cmake.install(build_type="Release")

    # Package contains its own cmake config file
    def package_info(self):
        self.cpp_info.set_property("skip_deps_file", True)
        self.cpp_info.set_property("cmake_config_file", True)

    def _pkg_bin(self, src_dir, dst_root, build_type, prefix):
        print(f"packaging source {src_dir} for {build_type}")
        dst_lib = Path(dst_root, f"lib/{build_type}")
        dst_bin = Path(dst_root, f"bin/{build_type}")

        print("Package dll (if any)")
        files.copy(self, f"{prefix}*.dll", src=src_dir, dst=dst_bin, keep_path=False)
        print("Package so versions (if any)")
        files.copy(self, f"{prefix}*.so.*", src=src_dir, dst=dst_lib, keep_path=False)
        print("Package so (if any)")
        files.copy(self, f"{prefix}*.so", src=src_dir, dst=dst_lib, keep_path=False)
        print("Package dylib (if any)")
        files.copy(self, f"{prefix}*.dylib", src=src_dir, dst=dst_lib, keep_path=False)
        print("Package a (archive) (if any)")
        files.copy(self, "*.a", src=src_dir, dst=dst_lib, keep_path=False)
        if ((build_type == "Debug") or (build_type == "RelWithDebInfo")) and (
            self.settings.compiler == "Visual Studio"
        ):
            # the debug info
            print("Adding pdb files for Windows debug")
            files.copy(self, f"{prefix}*.pdb", src=src_dir, dst=dst_bin, keep_path=False)


    def package(self):
        print(f"Package folder: {self.package_folder}")
        # The default sub folder created by conan in include is called "xeus-zmq"
        # based on the package name. Usually this is correct but in this case other
        # xeus packages assume that the folder is called "xeus".
        print(f"Self copy status (FileCopier) {self.copy._src_folders} {self.copy._dst_folder}") 
        copytree(Path(self.copy._src_folders[0], "xeus-zmq/include/xeus-zmq"), Path(self.copy._dst_folder, 'include/xeus'), ignore=ignore_patterns('*.cpp'))

        print("packaging zmq Debug")
        self._pkg_bin(f"{self.build_folder}/libzmq/lib/Debug", self.package_folder, "Debug", "libzmq")
        print("packaging zmq Release")
        self._pkg_bin(f"{self.build_folder}/libzmq/lib/Release", self.package_folder, "Release", "libzmq")
        if self.settings.os == "Windows":
            print("packaging zmq Debug")
            self._pkg_bin(f"{self.build_folder}/libzmq/bin/Debug", self.package_folder, "Debug", "libzmq")
            print("packaging zmq Release")
            self._pkg_bin(f"{self.build_folder}/libzmq/bin/Release", self.package_folder, "Release", "libzmq")
        # Cleanup unclassified libzmq artifacts
        files.rm(self, "libzmq*", Path(self.package_folder, 'lib') )

        # Move zmq CMake
        if self.settings.os == "Windows":
            copytree(Path(self.package_folder, "CMake"), Path(self.package_folder, "lib", "cmake", "libzmq"))
            rmtree(Path(self.package_folder, "CMake"))





        


